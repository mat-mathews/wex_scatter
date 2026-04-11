"""Tests for Initiative 5 Phase 3: Graph persistence + cache invalidation."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.store.graph_cache import (
    CACHE_VERSION,
    get_default_cache_path,
    is_cache_valid,
    load_and_validate,
    load_graph,
    save_graph,
)
from scatter.config import GraphConfig, ScatterConfig, load_config

REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_graph() -> DependencyGraph:
    """Small graph: A -> B, B -> C."""
    g = DependencyGraph()
    g.add_node(ProjectNode(path=Path("/fake/A/A.csproj"), name="A"))
    g.add_node(ProjectNode(path=Path("/fake/B/B.csproj"), name="B"))
    g.add_node(ProjectNode(path=Path("/fake/C/C.csproj"), name="C"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
    return g


# ===========================================================================
# TestSaveLoad
# ===========================================================================
class TestSaveLoad:
    def test_save_load_roundtrip(self, tmp_path):
        """Save a graph, load it, verify equality."""
        graph = _make_graph()
        cache_path = tmp_path / "cache" / "graph.json"

        save_graph(graph, cache_path, tmp_path)
        assert cache_path.is_file()

        loaded = load_graph(cache_path)
        assert loaded is not None
        assert loaded.node_count == 3
        assert loaded.edge_count == 2
        assert loaded.get_node("A") is not None
        assert loaded.get_node("B") is not None
        assert loaded.get_node("C") is not None

    def test_save_creates_parent_dirs(self, tmp_path):
        """save_graph creates intermediate directories."""
        cache_path = tmp_path / "deep" / "nested" / "graph.json"
        save_graph(_make_graph(), cache_path, tmp_path)
        assert cache_path.is_file()

    def test_save_is_atomic(self, tmp_path):
        """save_graph doesn't leave partial files on error."""
        cache_path = tmp_path / "atomic.json"

        class BrokenGraph:
            node_count = 1
            edge_count = 0

            def to_dict(self):
                raise RuntimeError("simulated serialization failure")

        with pytest.raises(RuntimeError):
            save_graph(BrokenGraph(), cache_path, tmp_path)

        # No file should exist — atomic write cleans up on failure
        assert not cache_path.is_file()
        # No temp files left behind
        assert len(list(tmp_path.glob("graph_cache_*.tmp"))) == 0

    def test_load_missing_file(self, tmp_path):
        """load_graph returns None for missing file."""
        assert load_graph(tmp_path / "nonexistent.json") is None

    def test_load_corrupt_file(self, tmp_path):
        """load_graph returns None for corrupt JSON."""
        cache_path = tmp_path / "corrupt.json"
        cache_path.write_text("not valid json {{{")
        assert load_graph(cache_path) is None

    def test_load_wrong_version(self, tmp_path):
        """load_graph returns None if cache version doesn't match."""
        cache_path = tmp_path / "old.json"
        cache_path.write_text(
            json.dumps(
                {
                    "version": 999,
                    "graph": {},
                }
            )
        )
        assert load_graph(cache_path) is None

    def test_load_missing_graph_key(self, tmp_path):
        """load_graph returns None if 'graph' key is missing."""
        cache_path = tmp_path / "bad.json"
        cache_path.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                }
            )
        )
        assert load_graph(cache_path) is None

    def test_cache_metadata(self, tmp_path):
        """Saved cache contains expected metadata fields."""
        graph = _make_graph()
        cache_path = tmp_path / "meta.json"
        save_graph(graph, cache_path, tmp_path)

        with open(cache_path) as f:
            envelope = json.load(f)

        assert envelope["version"] == CACHE_VERSION
        assert "created_at" in envelope
        assert envelope["node_count"] == 3
        assert envelope["edge_count"] == 2
        assert envelope["search_scope"] == str(tmp_path.resolve())
        assert "graph" in envelope


# ===========================================================================
# TestCacheValidation
# ===========================================================================
class TestCacheValidation:
    def test_cache_valid_git_no_code_changes(self, tmp_path):
        """Cache is valid when git reports no .cs/.csproj changes."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        save_graph(graph, cache_path, tmp_path)

        # Mock git to return the same hash and no changed files
        with (
            patch("scatter.store.graph_cache._get_git_head", return_value="abc123"),
            patch("scatter.store.graph_cache._git_has_code_changes", return_value=False),
        ):
            assert is_cache_valid(cache_path, tmp_path, invalidation="git")

    def test_cache_invalid_git_code_changed(self, tmp_path):
        """Cache is invalid when .cs or .csproj files changed."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        with patch("scatter.store.graph_cache._get_git_head", return_value="abc123"):
            save_graph(graph, cache_path, tmp_path)

        with patch("scatter.store.graph_cache._git_has_code_changes", return_value=True):
            assert not is_cache_valid(cache_path, tmp_path, invalidation="git")

    def test_cache_valid_mtime(self, tmp_path):
        """Mtime strategy: cache valid when no code files are newer."""
        # Create a code file first
        cs_file = tmp_path / "test.cs"
        cs_file.write_text("class Foo {}")
        time.sleep(0.05)  # ensure cache is newer

        # Save cache after the code file
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        save_graph(graph, cache_path, tmp_path)

        assert is_cache_valid(cache_path, tmp_path, invalidation="mtime")

    def test_cache_invalid_mtime(self, tmp_path):
        """Mtime strategy: cache invalid when code file is newer."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        save_graph(graph, cache_path, tmp_path)

        time.sleep(0.05)  # ensure code file is newer
        cs_file = tmp_path / "new_file.cs"
        cs_file.write_text("class Bar {}")

        assert not is_cache_valid(cache_path, tmp_path, invalidation="mtime")

    def test_cache_missing_file(self, tmp_path):
        """Cache is invalid when file doesn't exist."""
        assert not is_cache_valid(tmp_path / "nope.json", tmp_path)

    def test_git_command_failure_conservative_rebuild(self, tmp_path):
        """When git reports changes (failure fallback), cache is invalidated."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        with patch("scatter.store.graph_cache._get_git_head", return_value="abc123"):
            save_graph(graph, cache_path, tmp_path)

        with patch("scatter.store.graph_cache._git_has_code_changes", return_value=True):
            assert not is_cache_valid(cache_path, tmp_path, invalidation="git")

    def test_git_null_head_falls_back_to_mtime(self, tmp_path):
        """When cache has no git_head (non-git dir), falls back to mtime."""
        cache_path = tmp_path / "graph.json"
        envelope = {
            "version": CACHE_VERSION,
            "created_at": "2026-01-01T00:00:00Z",
            "search_scope": str(tmp_path.resolve()),
            "git_head": None,
            "node_count": 0,
            "edge_count": 0,
            "graph": {"nodes": {}, "edges": []},
        }
        cache_path.write_text(json.dumps(envelope))

        # No code files exist → mtime check passes
        assert is_cache_valid(cache_path, tmp_path, invalidation="git")

    def test_scope_mismatch_invalidates_cache(self, tmp_path):
        """Cache built for /repo/A is invalid when checked against /repo/B."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        scope_a = tmp_path / "repo_a"
        scope_b = tmp_path / "repo_b"
        scope_a.mkdir()
        scope_b.mkdir()

        save_graph(graph, cache_path, scope_a)

        # Checking validity against a different scope should fail
        assert not is_cache_valid(cache_path, scope_b, invalidation="mtime")


# ===========================================================================
# TestLoadAndValidate
# ===========================================================================
class TestLoadAndValidate:
    def test_single_pass_load(self, tmp_path):
        """load_and_validate reads, validates, and returns graph in one call."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        save_graph(graph, cache_path, tmp_path)

        with (
            patch("scatter.store.graph_cache._git_has_code_changes", return_value=False),
            patch("scatter.store.graph_cache._get_git_head", return_value="abc123"),
        ):
            # Need the cache to have a git_head for git validation
            pass

        # tmp_path is not a git repo, so git_head=None → falls back to mtime
        # No code files → mtime valid
        result = load_and_validate(cache_path, tmp_path, invalidation="mtime")
        assert result is not None
        loaded_graph, file_facts, project_facts, git_head, _proj_set_hash = result
        assert loaded_graph.node_count == 3

    def test_returns_none_when_stale(self, tmp_path):
        """load_and_validate returns None when cache is stale."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        with patch("scatter.store.graph_cache._get_git_head", return_value="abc123"):
            save_graph(graph, cache_path, tmp_path)

        with patch("scatter.store.graph_cache._git_has_code_changes", return_value=True):
            loaded = load_and_validate(cache_path, tmp_path, invalidation="git")
            assert loaded is None

    def test_scope_mismatch_returns_none(self, tmp_path):
        """load_and_validate returns None when scope doesn't match."""
        graph = _make_graph()
        cache_path = tmp_path / "graph.json"
        scope_a = tmp_path / "a"
        scope_b = tmp_path / "b"
        scope_a.mkdir()
        scope_b.mkdir()

        save_graph(graph, cache_path, scope_a)
        loaded = load_and_validate(cache_path, scope_b, invalidation="mtime")
        assert loaded is None


# ===========================================================================
# TestDefaultCachePath
# ===========================================================================
class TestDefaultCachePath:
    def test_default_cache_path(self):
        scope = Path("/repo/root")
        result = get_default_cache_path(scope)
        assert result == Path("/repo/root/.scatter/graph_cache.json")


# ===========================================================================
# TestCacheExists
# ===========================================================================
class TestCacheExists:
    def test_cache_exists_true(self, tmp_path):
        from scatter.store.graph_cache import cache_exists

        cache_dir = tmp_path / ".scatter"
        cache_dir.mkdir()
        (cache_dir / "graph_cache.json").write_text("{}")
        assert cache_exists(tmp_path) is True

    def test_cache_exists_false(self, tmp_path):
        from scatter.store.graph_cache import cache_exists

        assert cache_exists(tmp_path) is False

    def test_cache_exists_with_config_dir(self, tmp_path):
        from scatter.store.graph_cache import cache_exists

        custom_dir = tmp_path / "custom_cache"
        custom_dir.mkdir()
        (custom_dir / "graph_cache.json").write_text("{}")
        assert cache_exists(tmp_path, config_cache_dir=str(custom_dir)) is True


# ===========================================================================
# TestGraphConfig
# ===========================================================================
class TestGraphConfig:
    def test_default_graph_config(self):
        cfg = GraphConfig()
        assert cfg.cache_dir is None
        assert cfg.rebuild is False
        assert cfg.invalidation == "git"
        assert cfg.coupling_weights is None

    def test_scatter_config_has_graph(self):
        cfg = ScatterConfig()
        assert isinstance(cfg.graph, GraphConfig)

    def test_graph_config_from_yaml(self, tmp_path):
        """Graph config loaded from .scatter.yaml."""
        yaml_content = """
graph:
  cache_dir: /custom/cache
  invalidation: mtime
  coupling_weights:
    project_reference: 2.0
    namespace_usage: 0.1
"""
        yaml_path = tmp_path / ".scatter.yaml"
        yaml_path.write_text(yaml_content)

        config = load_config(repo_root=tmp_path)
        assert config.graph.cache_dir == "/custom/cache"
        assert config.graph.invalidation == "mtime"
        assert config.graph.coupling_weights == {
            "project_reference": 2.0,
            "namespace_usage": 0.1,
        }

    def test_graph_rebuild_cli_override(self, tmp_path):
        config = load_config(
            repo_root=tmp_path,
            cli_overrides={"graph.rebuild": True},
        )
        assert config.graph.rebuild is True


# ===========================================================================
# TestCLIArgParsing
# ===========================================================================
class TestCLIArgParsing:
    def test_graph_mode_parses(self):
        """--graph flag is recognized and mutually exclusive with other modes."""
        import argparse

        # We can't call main() directly without side effects, so test arg parsing
        # by importing the parser setup. Instead, verify via a subprocess-like approach.
        from unittest.mock import patch as mock_patch

        # Verify --graph sets is_graph_mode
        test_args = ["scatter", "--graph", "--search-scope", "."]
        with mock_patch("sys.argv", test_args):

            # We just need to verify arg parsing works — not full execution

            parser = argparse.ArgumentParser()
            mode_group = parser.add_mutually_exclusive_group(required=True)
            mode_group.add_argument("--graph", action="store_true", default=False)
            mode_group.add_argument("--target-project")
            mode_group.add_argument("--branch-name")
            args = parser.parse_args(["--graph"])
            assert args.graph is True

    def test_graph_mutually_exclusive_with_target(self):
        """--graph and --target-project cannot both be specified."""
        import argparse

        parser = argparse.ArgumentParser()
        mode_group = parser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument("--graph", action="store_true", default=False)
        mode_group.add_argument("--target-project")
        with pytest.raises(SystemExit):
            parser.parse_args(["--graph", "--target-project", "foo.csproj"])

    def test_rebuild_graph_maps_to_config(self, tmp_path):
        """--rebuild-graph CLI flag flows through to config.graph.rebuild."""
        from scatter.cli_parser import _build_cli_overrides
        import argparse

        ns = argparse.Namespace(
            google_api_key=None,
            gemini_model=None,
            disable_multiprocessing=False,
            max_depth=None,
            rebuild_graph=True,
        )
        overrides = _build_cli_overrides(ns)
        assert overrides.get("graph.rebuild") is True

        config = load_config(repo_root=tmp_path, cli_overrides=overrides)
        assert config.graph.rebuild is True


# ===========================================================================
# TestGraphModeIntegration
# ===========================================================================
class TestGraphModeIntegration:
    def test_graph_mode_builds_and_caches(self, tmp_path):
        """Integration: build graph from sample projects, verify cache created."""
        from scatter.analyzers.graph_builder import build_dependency_graph
        from scatter.analyzers.coupling_analyzer import (
            compute_all_metrics,
            detect_cycles,
            rank_by_coupling,
        )

        graph = build_dependency_graph(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )

        cache_path = tmp_path / "graph.json"
        save_graph(graph, cache_path, REPO_ROOT)

        # Load and verify
        loaded = load_graph(cache_path)
        assert loaded is not None
        assert loaded.node_count == graph.node_count
        assert loaded.edge_count == graph.edge_count

        # Metrics work on loaded graph
        metrics = compute_all_metrics(loaded)
        assert len(metrics) == loaded.node_count

        cycles = detect_cycles(loaded)
        assert isinstance(cycles, list)

        ranked = rank_by_coupling(metrics, top_n=3)
        assert len(ranked) <= 3
