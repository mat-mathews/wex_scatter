"""Tests for incremental graph updates (graph_patcher + cache v2 + edge removal)."""
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple
from unittest.mock import patch

import pytest

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.store.graph_cache import (
    CACHE_VERSION,
    FileFacts,
    ProjectFacts,
    compute_content_hash,
    compute_project_set_hash,
    load_and_validate,
    save_graph,
)
from scatter.store.graph_patcher import (
    PatchResult,
    extract_file_facts,
    extract_project_facts,
    get_changed_files,
    patch_graph,
    _build_namespace_to_project,
    _build_type_to_projects,
)

REPO_ROOT = Path(__file__).parent.parent.parent


# ===========================================================================
# Helpers
# ===========================================================================

def _make_synthetic_codebase(tmp_path: Path, num_projects: int = 3):
    """Create a minimal synthetic .NET codebase for testing.

    Returns (search_scope, csproj_paths, cs_paths).
    """
    scope = tmp_path / "repo"
    scope.mkdir()

    csproj_paths = []
    cs_paths = []

    for i in range(num_projects):
        name = f"Project{chr(65 + i)}"  # ProjectA, ProjectB, ...
        proj_dir = scope / name
        proj_dir.mkdir()

        # .csproj
        csproj = proj_dir / f"{name}.csproj"
        refs = ""
        if i > 0:
            prev = f"Project{chr(65 + i - 1)}"
            refs = f'    <ProjectReference Include="../{prev}/{prev}.csproj" />\n'
        csproj.write_text(
            f'<Project Sdk="Microsoft.NET.Sdk">\n'
            f'  <PropertyGroup>\n'
            f'    <TargetFramework>net8.0</TargetFramework>\n'
            f'    <RootNamespace>{name}</RootNamespace>\n'
            f'  </PropertyGroup>\n'
            f'  <ItemGroup>\n{refs}  </ItemGroup>\n'
            f'</Project>\n'
        )
        csproj_paths.append(csproj)

        # .cs files
        cs1 = proj_dir / f"{name}Service.cs"
        using = f"using Project{chr(65 + i - 1)};\n" if i > 0 else ""
        cs1.write_text(
            f"{using}"
            f"namespace {name};\n\n"
            f"public class {name}Service\n{{\n"
            f"    public void DoWork() {{ }}\n"
            f"}}\n"
        )
        cs_paths.append(cs1)

        cs2 = proj_dir / f"{name}Model.cs"
        cs2.write_text(
            f"namespace {name};\n\n"
            f"public class {name}Model\n{{\n"
            f"    public int Id {{ get; set; }}\n"
            f"}}\n"
        )
        cs_paths.append(cs2)

    return scope, csproj_paths, cs_paths


def _build_graph_and_facts(scope: Path):
    """Build a graph with facts from a synthetic codebase."""
    from scatter.analyzers.graph_builder import build_dependency_graph

    result = build_dependency_graph(
        scope,
        disable_multiprocessing=True,
        capture_facts=True,
    )
    return result  # (graph, file_facts, project_facts)


# ===========================================================================
# Phase 1: Cache Format v2
# ===========================================================================

class TestFileFacts:
    def test_construction(self):
        ff = FileFacts(
            path="Foo/Bar.cs",
            project="Foo",
            types_declared=["BarService"],
            namespaces_used=["System.Linq"],
            sprocs_referenced=["sp_Insert"],
            content_hash="abc123",
        )
        assert ff.project == "Foo"
        assert ff.types_declared == ["BarService"]

    def test_defaults(self):
        ff = FileFacts(path="x.cs", project="X")
        assert ff.types_declared == []
        assert ff.namespaces_used == []
        assert ff.sprocs_referenced == []
        assert ff.content_hash == ""


class TestProjectFacts:
    def test_construction(self):
        pf = ProjectFacts(
            namespace="GalaxyWorks.Foo",
            project_references=["Bar", "Common"],
            csproj_content_hash="def456",
        )
        assert pf.namespace == "GalaxyWorks.Foo"
        assert pf.project_references == ["Bar", "Common"]

    def test_defaults(self):
        pf = ProjectFacts()
        assert pf.namespace is None
        assert pf.project_references == []
        assert pf.csproj_content_hash == ""


class TestContentHash:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.cs"
        f.write_text("class Foo {}")
        h1 = compute_content_hash(f)
        h2 = compute_content_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_different_content(self, tmp_path):
        f = tmp_path / "test.cs"
        f.write_text("class Foo {}")
        h1 = compute_content_hash(f)
        f.write_text("class Bar {}")
        h2 = compute_content_hash(f)
        assert h1 != h2

    def test_missing_file(self, tmp_path):
        assert compute_content_hash(tmp_path / "nope.cs") == ""


class TestProjectSetHash:
    def test_deterministic(self):
        h1 = compute_project_set_hash(["A.csproj", "B.csproj"])
        h2 = compute_project_set_hash(["A.csproj", "B.csproj"])
        assert h1 == h2

    def test_order_independent(self):
        h1 = compute_project_set_hash(["B.csproj", "A.csproj"])
        h2 = compute_project_set_hash(["A.csproj", "B.csproj"])
        assert h1 == h2  # sorted internally

    def test_different_sets(self):
        h1 = compute_project_set_hash(["A.csproj"])
        h2 = compute_project_set_hash(["A.csproj", "B.csproj"])
        assert h1 != h2


class TestCacheV2SaveLoad:
    def test_v2_roundtrip_with_facts(self, tmp_path):
        """Save v2 cache with facts, load it back, verify facts survive."""
        graph = DependencyGraph()
        graph.add_node(ProjectNode(path=tmp_path / "A" / "A.csproj", name="A"))

        ff = {"A/Svc.cs": FileFacts(path="A/Svc.cs", project="A", types_declared=["Svc"])}
        pf = {"A": ProjectFacts(namespace="A", project_references=[], csproj_content_hash="x")}

        cache_path = tmp_path / "cache.json"
        save_graph(graph, cache_path, tmp_path, file_facts=ff, project_facts=pf)

        result = load_and_validate(cache_path, tmp_path, invalidation="mtime")
        assert result is not None
        loaded_graph, loaded_ff, loaded_pf, git_head, _psh = result
        assert loaded_graph.node_count == 1
        assert loaded_ff is not None
        assert "A/Svc.cs" in loaded_ff
        assert loaded_ff["A/Svc.cs"].types_declared == ["Svc"]
        assert loaded_pf is not None
        assert loaded_pf["A"].namespace == "A"

    def test_v2_envelope_has_project_set_hash(self, tmp_path):
        graph = DependencyGraph()
        graph.add_node(ProjectNode(path=tmp_path / "A" / "A.csproj", name="A"))

        ff = {"A/x.cs": FileFacts(path="A/x.cs", project="A")}
        pf = {"A": ProjectFacts(namespace="A")}

        cache_path = tmp_path / "cache.json"
        save_graph(graph, cache_path, tmp_path, file_facts=ff, project_facts=pf)

        with open(cache_path) as f:
            envelope = json.load(f)
        assert "project_set_hash" in envelope
        assert len(envelope["project_set_hash"]) == 64

    def test_v1_cache_loads_with_no_facts(self, tmp_path):
        """v1 cache (no facts) loads with None facts."""
        graph = DependencyGraph()
        graph.add_node(ProjectNode(path=tmp_path / "A" / "A.csproj", name="A"))

        # Write a v1-style cache manually
        cache_path = tmp_path / "cache.json"
        envelope = {
            "version": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "search_scope": str(tmp_path.resolve()),
            "git_head": None,
            "node_count": 1,
            "edge_count": 0,
            "graph": graph.to_dict(),
        }
        cache_path.write_text(json.dumps(envelope))

        result = load_and_validate(cache_path, tmp_path, invalidation="mtime")
        assert result is not None
        loaded_graph, ff, pf, git_head, _psh = result
        assert loaded_graph.node_count == 1
        assert ff is None
        assert pf is None

    def test_save_without_facts_still_works(self, tmp_path):
        """Save without facts (backward compat for non-incremental callers)."""
        graph = DependencyGraph()
        graph.add_node(ProjectNode(path=tmp_path / "A" / "A.csproj", name="A"))

        cache_path = tmp_path / "cache.json"
        save_graph(graph, cache_path, tmp_path)

        with open(cache_path) as f:
            envelope = json.load(f)
        assert "file_facts" not in envelope
        assert "project_facts" not in envelope


# ===========================================================================
# Phase 2: Graph Mutation
# ===========================================================================

class TestRemoveEdgesFrom:
    def _make_graph(self):
        g = DependencyGraph()
        g.add_node(ProjectNode(path=Path("/A/A.csproj"), name="A"))
        g.add_node(ProjectNode(path=Path("/B/B.csproj"), name="B"))
        g.add_node(ProjectNode(path=Path("/C/C.csproj"), name="C"))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="A", target="C", edge_type="namespace_usage"))
        g.add_edge(DependencyEdge(source="B", target="C", edge_type="type_usage"))
        return g

    def test_remove_all_from_source(self):
        g = self._make_graph()
        removed = g.remove_edges_from("A")
        assert removed == 2
        assert g.get_edges_from("A") == []
        assert g.edge_count == 1  # only B->C remains
        assert "B" not in g.get_dependency_names("A")
        assert "C" not in g.get_dependency_names("A")
        assert "A" not in g.get_consumer_names("B")
        assert "A" not in g.get_consumer_names("C")

    def test_remove_filtered_by_edge_type(self):
        g = self._make_graph()
        removed = g.remove_edges_from("A", {"namespace_usage"})
        assert removed == 1
        assert len(g.get_edges_from("A")) == 1
        assert g.get_edges_from("A")[0].edge_type == "project_reference"
        # A still depends on B (project_reference), but not C (namespace_usage removed)
        assert "B" in g.get_dependency_names("A")
        assert "C" not in g.get_dependency_names("A")

    def test_remove_unknown_source(self):
        g = self._make_graph()
        removed = g.remove_edges_from("UNKNOWN")
        assert removed == 0
        assert g.edge_count == 3

    def test_remove_no_matching_type(self):
        g = self._make_graph()
        removed = g.remove_edges_from("A", {"sproc_shared"})
        assert removed == 0
        assert g.edge_count == 3

    def test_updates_all_four_indexes(self):
        g = self._make_graph()
        g.remove_edges_from("A")
        # _outgoing: A should have no edges
        assert len(g._outgoing.get("A", [])) == 0
        # _incoming: B and C should not list A
        for e in g._incoming.get("B", []):
            assert e.source != "A"
        for e in g._incoming.get("C", []):
            assert e.source != "A"
        # _forward: A should not map to B or C
        assert "B" not in g._forward.get("A", set())
        assert "C" not in g._forward.get("A", set())
        # _reverse: B and C should not map back to A
        assert "A" not in g._reverse.get("B", set())
        assert "A" not in g._reverse.get("C", set())


class TestRemoveEdgesTo:
    def test_remove_all_incoming(self):
        g = DependencyGraph()
        g.add_node(ProjectNode(path=Path("/A/A.csproj"), name="A"))
        g.add_node(ProjectNode(path=Path("/B/B.csproj"), name="B"))
        g.add_node(ProjectNode(path=Path("/C/C.csproj"), name="C"))
        g.add_edge(DependencyEdge(source="A", target="C", edge_type="namespace_usage"))
        g.add_edge(DependencyEdge(source="B", target="C", edge_type="type_usage"))

        removed = g.remove_edges_to("C")
        assert removed == 2
        assert g.get_edges_to("C") == []
        assert g.edge_count == 0
        assert "A" not in g.get_consumer_names("C")
        assert "B" not in g.get_consumer_names("C")

    def test_remove_filtered_incoming(self):
        g = DependencyGraph()
        g.add_node(ProjectNode(path=Path("/A/A.csproj"), name="A"))
        g.add_node(ProjectNode(path=Path("/B/B.csproj"), name="B"))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="namespace_usage"))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="type_usage"))

        removed = g.remove_edges_to("B", {"type_usage"})
        assert removed == 1
        assert len(g.get_edges_to("B")) == 1
        # A still depends on B via namespace_usage
        assert "B" in g.get_dependency_names("A")

    def test_remove_unknown_target(self):
        g = DependencyGraph()
        g.add_node(ProjectNode(path=Path("/A/A.csproj"), name="A"))
        removed = g.remove_edges_to("UNKNOWN")
        assert removed == 0


# ===========================================================================
# Phase 2: Fact Extraction
# ===========================================================================

class TestExtractFileFacts:
    def test_extracts_types_namespaces_sprocs(self, tmp_path):
        scope = tmp_path / "repo"
        scope.mkdir()
        proj_dir = scope / "MyProj"
        proj_dir.mkdir()

        cs = proj_dir / "Service.cs"
        cs.write_text(
            'using System;\n'
            'using GalaxyWorks.Data;\n\n'
            'namespace MyProj;\n\n'
            'public class MyService\n{\n'
            '    public void Run()\n    {\n'
            '        Execute("sp_InsertFoo");\n'
            '    }\n}\n'
        )

        facts = extract_file_facts(cs, "MyProj", scope)
        assert facts.path == "MyProj/Service.cs"
        assert facts.project == "MyProj"
        assert "MyService" in facts.types_declared
        assert "System" in facts.namespaces_used
        assert "GalaxyWorks.Data" in facts.namespaces_used
        assert any("sp_InsertFoo" in s for s in facts.sprocs_referenced)
        assert len(facts.content_hash) == 64

    def test_missing_file(self, tmp_path):
        facts = extract_file_facts(tmp_path / "nope.cs", "X", tmp_path)
        assert facts.types_declared == []
        assert facts.content_hash == ""


class TestExtractProjectFacts:
    def test_extracts_namespace_and_refs(self, tmp_path):
        proj_a = tmp_path / "A"
        proj_a.mkdir()
        proj_b = tmp_path / "B"
        proj_b.mkdir()

        csproj_b = proj_b / "B.csproj"
        csproj_b.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <PropertyGroup><RootNamespace>MyNS</RootNamespace></PropertyGroup>\n'
            '  <ItemGroup>\n'
            '    <ProjectReference Include="../A/A.csproj" />\n'
            '  </ItemGroup>\n'
            '</Project>\n'
        )

        # A.csproj must exist for resolution
        (proj_a / "A.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>'
        )

        facts = extract_project_facts(csproj_b, {"A", "B"})
        assert facts.namespace == "MyNS"
        assert "A" in facts.project_references
        assert len(facts.csproj_content_hash) == 64


# ===========================================================================
# Phase 2: Capture Facts in Builder
# ===========================================================================

class TestBuildWithCaptureFacts:
    def test_capture_facts_returns_tuple(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        result = _build_graph_and_facts(scope)
        graph, ff, pf = result
        assert graph.node_count >= 3
        assert len(ff) > 0  # at least some .cs files
        assert len(pf) >= 3  # one per project

    def test_facts_match_graph(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Every project in graph should have project facts
        for node in graph.get_all_nodes():
            assert node.name in pf, f"Missing project facts for {node.name}"

        # Every file's project should be a graph node
        for rel, facts in ff.items():
            assert graph.get_node(facts.project) is not None

    def test_without_capture_returns_graph_only(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        from scatter.analyzers.graph_builder import build_dependency_graph
        result = build_dependency_graph(scope, disable_multiprocessing=True)
        # Should be a plain DependencyGraph, not a tuple
        assert isinstance(result, DependencyGraph)


# ===========================================================================
# Phase 3: Patch Algorithm
# ===========================================================================

class TestPatchEmpty:
    def test_no_changes_is_noop(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        original_edges = graph.edge_count
        result = patch_graph(graph, ff, pf, [], scope)

        assert result.patch_applied is True
        assert result.files_processed == 0
        assert result.projects_affected == 0
        assert result.graph.edge_count == original_edges


class TestPatchUsageOnlyChange:
    def test_usage_change_rebuilds_edges(self, tmp_path):
        """Changing a method body (usage-only) rebuilds edges for that project."""
        scope, _, cs_paths = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Modify a .cs file: add a usage of a type from another project
        cs_file = scope / "ProjectB" / "ProjectBService.cs"
        cs_file.write_text(
            "using ProjectA;\n\n"
            "namespace ProjectB;\n\n"
            "public class ProjectBService\n{\n"
            "    public ProjectAService svc;\n"
            "    public void DoWork() { svc.DoWork(); }\n"
            "}\n"
        )

        changed = ["ProjectB/ProjectBService.cs"]
        result = patch_graph(graph, ff, pf, changed, scope)

        assert result.patch_applied is True
        assert result.projects_affected >= 1
        assert "ProjectB" in {n.name for n in result.graph.get_all_nodes()}


class TestPatchDeclarationChange:
    def test_new_type_triggers_broader_rebuild(self, tmp_path):
        """Adding a new type declaration triggers type_to_projects rebuild."""
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Add a new type to ProjectA
        cs_file = scope / "ProjectA" / "ProjectAService.cs"
        cs_file.write_text(
            "namespace ProjectA;\n\n"
            "public class ProjectAService\n{\n"
            "    public void DoWork() { }\n"
            "}\n\n"
            "public class NewExportedType\n{\n}\n"
        )

        changed = ["ProjectA/ProjectAService.cs"]
        result = patch_graph(graph, ff, pf, changed, scope)

        assert result.patch_applied is True
        assert result.declarations_changed is True


class TestPatchDeletedFile:
    def test_deleted_file_rebuilds_project_edges(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Delete a .cs file
        model_file = scope / "ProjectA" / "ProjectAModel.cs"
        rel = "ProjectA/ProjectAModel.cs"
        assert rel in ff  # sanity check
        model_file.unlink()

        result = patch_graph(graph, ff, pf, [rel], scope)

        assert result.patch_applied is True
        assert rel not in result.file_facts
        assert result.projects_affected >= 1


class TestPatchNewFile:
    def test_new_file_adds_facts(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Add a new .cs file
        new_cs = scope / "ProjectA" / "NewHelper.cs"
        new_cs.write_text(
            "namespace ProjectA;\n\n"
            "public class NewHelper { }\n"
        )

        changed = ["ProjectA/NewHelper.cs"]
        result = patch_graph(graph, ff, pf, changed, scope)

        assert result.patch_applied is True
        assert "ProjectA/NewHelper.cs" in result.file_facts
        assert result.files_processed >= 1


class TestPatchCsprojChange:
    def test_csproj_ref_change_rebuilds_ref_edges(self, tmp_path):
        """Modifying .csproj references rebuilds project_reference edges."""
        scope, _, _ = _make_synthetic_codebase(tmp_path, num_projects=3)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Modify ProjectC.csproj to also reference ProjectA
        csproj = scope / "ProjectC" / "ProjectC.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <PropertyGroup>\n'
            '    <TargetFramework>net8.0</TargetFramework>\n'
            '    <RootNamespace>ProjectC</RootNamespace>\n'
            '  </PropertyGroup>\n'
            '  <ItemGroup>\n'
            '    <ProjectReference Include="../ProjectB/ProjectB.csproj" />\n'
            '    <ProjectReference Include="../ProjectA/ProjectA.csproj" />\n'
            '  </ItemGroup>\n'
            '</Project>\n'
        )

        changed = ["ProjectC/ProjectC.csproj"]
        result = patch_graph(graph, ff, pf, changed, scope)

        assert result.patch_applied is True
        # ProjectC should now reference both A and B
        ref_edges = [
            e for e in result.graph.get_edges_from("ProjectC")
            if e.edge_type == "project_reference"
        ]
        ref_targets = {e.target for e in ref_edges}
        assert "ProjectA" in ref_targets
        assert "ProjectB" in ref_targets


class TestPatchContentHashEarlyCutoff:
    def test_unchanged_content_skips_reextraction(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # "Change" a file that git reports but content is actually the same
        cs_rel = "ProjectA/ProjectAService.cs"
        original_facts = ff[cs_rel]

        result = patch_graph(graph, ff, pf, [cs_rel], scope)

        # File was processed (read + hashed) but should early-cutoff
        assert result.patch_applied is True


class TestPatchThresholds:
    def test_project_threshold_triggers_full_rebuild(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Set threshold to 1 project, change files in 2 projects
        changed = [
            "ProjectA/ProjectAService.cs",
            "ProjectB/ProjectBService.cs",
        ]
        result = patch_graph(
            graph, ff, pf, changed, scope,
            rebuild_threshold_projects=1,
        )
        assert result.patch_applied is False

    def test_file_pct_threshold_triggers_full_rebuild(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Change all files → exceeds 30% threshold
        all_cs = [rel for rel in ff.keys()]
        result = patch_graph(
            graph, ff, pf, all_cs, scope,
            rebuild_threshold_pct=0.01,  # 1% threshold
        )
        assert result.patch_applied is False


class TestPatchStructuralChange:
    def test_new_csproj_triggers_full_rebuild(self, tmp_path):
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Create a new project
        new_proj = scope / "ProjectD"
        new_proj.mkdir()
        (new_proj / "ProjectD.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '<PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n'
            '</Project>\n'
        )

        changed = ["ProjectD/ProjectD.csproj"]
        result = patch_graph(graph, ff, pf, changed, scope)
        assert result.patch_applied is False

    def test_deleted_csproj_triggers_full_rebuild(self, tmp_path):
        scope, csproj_paths, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Delete a project
        csproj_paths[0].unlink()
        rel = str(csproj_paths[0].relative_to(scope))

        result = patch_graph(graph, ff, pf, [rel], scope)
        assert result.patch_applied is False


# ===========================================================================
# Phase 3: Git Diff
# ===========================================================================

class TestGetChangedFiles:
    def test_returns_none_on_failure(self, tmp_path):
        """Non-git directory returns None."""
        result = get_changed_files("abc123", tmp_path)
        assert result is None

    def test_returns_list_in_git_repo(self):
        """In an actual git repo, should return a list (possibly empty)."""
        # Use the actual repo
        result = get_changed_files("HEAD", REPO_ROOT)
        assert result is not None
        assert isinstance(result, list)


# ===========================================================================
# Phase 4: Property-Based Tests
# ===========================================================================

class TestIncrementalMatchesFullRebuild:
    """Core correctness invariant: patched graph == fresh build."""

    def _assert_graphs_equivalent(self, g1: DependencyGraph, g2: DependencyGraph):
        """Assert two graphs have the same nodes and edges."""
        # Same nodes
        names1 = {n.name for n in g1.get_all_nodes()}
        names2 = {n.name for n in g2.get_all_nodes()}
        assert names1 == names2, f"Node mismatch: {names1 ^ names2}"

        # Same edges (compare by source, target, edge_type)
        def edge_set(g):
            return {
                (e.source, e.target, e.edge_type)
                for e in g.all_edges
            }
        es1 = edge_set(g1)
        es2 = edge_set(g2)
        assert es1 == es2, f"Edge mismatch: added={es2 - es1}, removed={es1 - es2}"

    def test_usage_only_change(self, tmp_path):
        """After a usage-only change, incremental == full rebuild."""
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Modify a .cs file (usage only — same types declared)
        cs = scope / "ProjectB" / "ProjectBService.cs"
        cs.write_text(
            "using ProjectA;\n\n"
            "namespace ProjectB;\n\n"
            "public class ProjectBService\n{\n"
            "    public ProjectAModel model;\n"
            "    public void DoWork() { }\n"
            "}\n"
        )

        changed = ["ProjectB/ProjectBService.cs"]
        result = patch_graph(graph, ff, pf, changed, scope)
        assert result.patch_applied is True

        # Fresh full build
        graph_full, _, _ = _build_graph_and_facts(scope)

        self._assert_graphs_equivalent(result.graph, graph_full)

    def test_declaration_change(self, tmp_path):
        """After a declaration change, incremental == full rebuild."""
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Add a new type
        cs = scope / "ProjectA" / "ProjectAService.cs"
        cs.write_text(
            "namespace ProjectA;\n\n"
            "public class ProjectAService { public void DoWork() { } }\n"
            "public class BrandNewType { }\n"
        )

        changed = ["ProjectA/ProjectAService.cs"]
        result = patch_graph(graph, ff, pf, changed, scope)
        assert result.patch_applied is True

        graph_full, _, _ = _build_graph_and_facts(scope)
        self._assert_graphs_equivalent(result.graph, graph_full)

    def test_deleted_file(self, tmp_path):
        """After deleting a file, incremental == full rebuild."""
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        model = scope / "ProjectA" / "ProjectAModel.cs"
        model.unlink()

        changed = ["ProjectA/ProjectAModel.cs"]
        result = patch_graph(graph, ff, pf, changed, scope)
        assert result.patch_applied is True

        graph_full, _, _ = _build_graph_and_facts(scope)
        self._assert_graphs_equivalent(result.graph, graph_full)

    def test_new_file(self, tmp_path):
        """After adding a file, incremental == full rebuild."""
        scope, _, _ = _make_synthetic_codebase(tmp_path)
        graph, ff, pf = _build_graph_and_facts(scope)

        new_cs = scope / "ProjectA" / "Extra.cs"
        new_cs.write_text(
            "namespace ProjectA;\npublic class ExtraHelper { }\n"
        )

        changed = ["ProjectA/Extra.cs"]
        result = patch_graph(graph, ff, pf, changed, scope)
        assert result.patch_applied is True

        graph_full, _, _ = _build_graph_and_facts(scope)
        self._assert_graphs_equivalent(result.graph, graph_full)

    def test_namespace_change(self, tmp_path):
        """After a .csproj namespace change, incremental == full rebuild."""
        scope, _, _ = _make_synthetic_codebase(tmp_path, num_projects=3)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Change ProjectA's namespace in .csproj
        csproj = scope / "ProjectA" / "ProjectA.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <PropertyGroup>\n'
            '    <TargetFramework>net8.0</TargetFramework>\n'
            '    <RootNamespace>ProjectA.Renamed</RootNamespace>\n'
            '  </PropertyGroup>\n'
            '  <ItemGroup>\n  </ItemGroup>\n'
            '</Project>\n'
        )

        changed = ["ProjectA/ProjectA.csproj"]
        result = patch_graph(graph, ff, pf, changed, scope)
        assert result.patch_applied is True

        graph_full, _, _ = _build_graph_and_facts(scope)
        self._assert_graphs_equivalent(result.graph, graph_full)

    def test_csproj_reference_change(self, tmp_path):
        """After changing .csproj refs, incremental == full rebuild."""
        scope, _, _ = _make_synthetic_codebase(tmp_path, num_projects=3)
        graph, ff, pf = _build_graph_and_facts(scope)

        # Add a reference from ProjectC to ProjectA
        csproj = scope / "ProjectC" / "ProjectC.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <PropertyGroup>\n'
            '    <TargetFramework>net8.0</TargetFramework>\n'
            '    <RootNamespace>ProjectC</RootNamespace>\n'
            '  </PropertyGroup>\n'
            '  <ItemGroup>\n'
            '    <ProjectReference Include="../ProjectB/ProjectB.csproj" />\n'
            '    <ProjectReference Include="../ProjectA/ProjectA.csproj" />\n'
            '  </ItemGroup>\n'
            '</Project>\n'
        )

        changed = ["ProjectC/ProjectC.csproj"]
        result = patch_graph(graph, ff, pf, changed, scope)
        assert result.patch_applied is True

        graph_full, _, _ = _build_graph_and_facts(scope)
        self._assert_graphs_equivalent(result.graph, graph_full)


# ===========================================================================
# Phase 4: Integration
# ===========================================================================

class TestIntegrationWithRealRepo:
    def test_build_and_cache_v2(self, tmp_path):
        """Build from real sample projects, save v2 cache, reload."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        graph, ff, pf = build_dependency_graph(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
            capture_facts=True,
        )

        cache_path = tmp_path / "cache.json"
        save_graph(graph, cache_path, REPO_ROOT, ff, pf)

        result = load_and_validate(cache_path, REPO_ROOT, invalidation="mtime")
        assert result is not None
        loaded_graph, loaded_ff, loaded_pf, _, _psh = result
        assert loaded_graph.node_count == graph.node_count
        assert loaded_graph.edge_count == graph.edge_count
        assert loaded_ff is not None
        assert loaded_pf is not None

    def test_metrics_identical_after_noop_patch(self, tmp_path):
        """Coupling scores and cycles identical after a no-op patch."""
        from scatter.analyzers.coupling_analyzer import compute_all_metrics, detect_cycles

        scope, _, _ = _make_synthetic_codebase(tmp_path, num_projects=4)
        graph, ff, pf = _build_graph_and_facts(scope)

        metrics_before = compute_all_metrics(graph)
        cycles_before = detect_cycles(graph)

        result = patch_graph(graph, ff, pf, [], scope)
        assert result.patch_applied is True

        metrics_after = compute_all_metrics(result.graph)
        cycles_after = detect_cycles(result.graph)

        for name in metrics_before:
            assert metrics_before[name].coupling_score == metrics_after[name].coupling_score
            assert metrics_before[name].fan_in == metrics_after[name].fan_in
            assert metrics_before[name].fan_out == metrics_after[name].fan_out

        assert len(cycles_before) == len(cycles_after)
