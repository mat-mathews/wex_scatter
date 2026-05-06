"""Tests for PR 2 Part B: .props/.targets change detection in git branch analysis."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scatter.analyzers.git_analyzer import (
    BranchChanges,
    ConfigFileChange,
    analyze_branch_changes,
)
from scatter.analysis import ModeResult, _build_import_reverse_index, run_git_analysis
from scatter.core.graph import DependencyGraph, ProjectNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(name: str, **kwargs) -> ProjectNode:
    defaults = {
        "path": Path(f"/fake/{name}/{name}.csproj"),
        "name": name,
    }
    defaults.update(kwargs)
    return ProjectNode(**defaults)


def _make_graph_with_imports(import_map: dict) -> DependencyGraph:
    """Build a graph where import_map is {project_name: [import_paths]}."""
    g = DependencyGraph()
    for name, imports in import_map.items():
        g.add_node(_make_node(name, msbuild_imports=imports))
    return g


# ===========================================================================
# TestConfigFileChange
# ===========================================================================


class TestConfigFileChange:
    def test_construction(self):
        c = ConfigFileChange(path="Directory.Build.props", change_type="M")
        assert c.path == "Directory.Build.props"
        assert c.change_type == "M"


# ===========================================================================
# TestBranchChangesCollection
# ===========================================================================


class TestBranchChangesCollection:
    def _mock_diff_item(self, a_path, b_path, change_type):
        item = MagicMock()
        item.a_path = a_path
        item.b_path = b_path
        item.change_type = change_type
        return item

    @patch("scatter.analyzers.git_analyzer.find_project_file")
    @patch("scatter.analyzers.git_analyzer.git")
    def test_props_collected(self, mock_git, mock_find):
        mock_repo = MagicMock()
        mock_git.Repo.return_value = mock_repo
        mock_repo.working_tree_dir = "/repo"

        base = MagicMock()
        feature = MagicMock()
        mock_repo.heads = {"main": MagicMock(commit=base), "feature/x": MagicMock(commit=feature)}
        # dict already supports `in` — no override needed
        mock_repo.merge_base.return_value = [base]

        diff_item = self._mock_diff_item("Directory.Build.props", "Directory.Build.props", "M")
        base.diff.return_value = [diff_item]

        result = analyze_branch_changes("/repo", "feature/x", "main")
        assert len(result.changed_config_files) == 1
        assert result.changed_config_files[0].path == "Directory.Build.props"
        assert result.changed_config_files[0].change_type == "M"

    @patch("scatter.analyzers.git_analyzer.find_project_file")
    @patch("scatter.analyzers.git_analyzer.git")
    def test_targets_collected(self, mock_git, mock_find):
        mock_repo = MagicMock()
        mock_git.Repo.return_value = mock_repo
        mock_repo.working_tree_dir = "/repo"

        base = MagicMock()
        feature = MagicMock()
        mock_repo.heads = {"main": MagicMock(commit=base), "feature/x": MagicMock(commit=feature)}
        # dict already supports `in` — no override needed
        mock_repo.merge_base.return_value = [base]

        diff_item = self._mock_diff_item("Directory.Build.targets", "Directory.Build.targets", "M")
        base.diff.return_value = [diff_item]

        result = analyze_branch_changes("/repo", "feature/x", "main")
        assert len(result.changed_config_files) == 1
        assert result.changed_config_files[0].path == "Directory.Build.targets"

    @patch("scatter.analyzers.git_analyzer.find_project_file")
    @patch("scatter.analyzers.git_analyzer.git")
    def test_deleted_props_uses_a_path(self, mock_git, mock_find):
        mock_repo = MagicMock()
        mock_git.Repo.return_value = mock_repo
        mock_repo.working_tree_dir = "/repo"

        base = MagicMock()
        feature = MagicMock()
        mock_repo.heads = {"main": MagicMock(commit=base), "feature/x": MagicMock(commit=feature)}
        # dict already supports `in` — no override needed
        mock_repo.merge_base.return_value = [base]

        diff_item = self._mock_diff_item("old/Directory.Build.props", None, "D")
        base.diff.return_value = [diff_item]

        result = analyze_branch_changes("/repo", "feature/x", "main")
        assert len(result.changed_config_files) == 1
        assert result.changed_config_files[0].path == "old/Directory.Build.props"
        assert result.changed_config_files[0].change_type == "D"

    @patch("scatter.analyzers.git_analyzer.find_project_file")
    @patch("scatter.analyzers.git_analyzer.git")
    def test_backslash_normalization(self, mock_git, mock_find):
        mock_repo = MagicMock()
        mock_git.Repo.return_value = mock_repo
        mock_repo.working_tree_dir = "/repo"

        base = MagicMock()
        feature = MagicMock()
        mock_repo.heads = {"main": MagicMock(commit=base), "feature/x": MagicMock(commit=feature)}
        # dict already supports `in` — no override needed
        mock_repo.merge_base.return_value = [base]

        diff_item = self._mock_diff_item(
            "build\\Directory.Build.props", "build\\Directory.Build.props", "M"
        )
        base.diff.return_value = [diff_item]

        result = analyze_branch_changes("/repo", "feature/x", "main")
        assert result.changed_config_files[0].path == "build/Directory.Build.props"

    @patch("scatter.analyzers.git_analyzer.find_project_file")
    @patch("scatter.analyzers.git_analyzer.git")
    def test_mixed_cs_and_props(self, mock_git, mock_find):
        mock_repo = MagicMock()
        mock_git.Repo.return_value = mock_repo
        mock_repo.working_tree_dir = "/repo"

        base = MagicMock()
        feature = MagicMock()
        mock_repo.heads = {"main": MagicMock(commit=base), "feature/x": MagicMock(commit=feature)}
        # dict already supports `in` — no override needed
        mock_repo.merge_base.return_value = [base]

        props_item = self._mock_diff_item("Directory.Build.props", "Directory.Build.props", "M")
        cs_item = self._mock_diff_item("Foo/Bar.cs", "Foo/Bar.cs", "M")
        base.diff.return_value = [props_item, cs_item]
        mock_find.return_value = "Foo/Foo.csproj"

        result = analyze_branch_changes("/repo", "feature/x", "main")
        assert len(result.changed_config_files) == 1
        assert "Foo/Foo.csproj" in result.project_changes
        assert result.project_changes["Foo/Foo.csproj"] == ["Foo/Bar.cs"]

    @patch("scatter.analyzers.git_analyzer.find_project_file")
    @patch("scatter.analyzers.git_analyzer.git")
    def test_from_analyzer(self, mock_git, mock_find):
        """Import from the analyzer module works."""
        from scatter.analyzers.git_analyzer import analyze_branch_changes as abc

        assert callable(abc)


# ===========================================================================
# TestImportReverseIndex
# ===========================================================================


class TestImportReverseIndex:
    def test_single_pass_index_build(self):
        g = _make_graph_with_imports(
            {
                "A": ["build/wex.common.props", "Directory.Build.props"],
                "B": ["build/wex.common.props"],
                "C": [],
            }
        )
        index = _build_import_reverse_index(g)
        assert sorted(index["build/wex.common.props"]) == ["A", "B"]
        assert index["Directory.Build.props"] == ["A"]
        assert "C" not in str(index.values())

    def test_normalizes_backslash(self):
        g = DependencyGraph()
        g.add_node(_make_node("X", msbuild_imports=["build\\wex.common.props"]))
        index = _build_import_reverse_index(g)
        assert "build/wex.common.props" in index
        assert "build\\wex.common.props" not in index

    def test_multiple_projects_same_import(self):
        g = _make_graph_with_imports(
            {
                "P1": ["shared.props"],
                "P2": ["shared.props"],
                "P3": ["shared.props"],
            }
        )
        index = _build_import_reverse_index(g)
        assert sorted(index["shared.props"]) == ["P1", "P2", "P3"]

    def test_empty_graph(self):
        g = DependencyGraph()
        index = _build_import_reverse_index(g)
        assert index == {}


# ===========================================================================
# TestPropsExpansionInGitAnalysis
# ===========================================================================


class TestPropsExpansionInGitAnalysis:
    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_props_impact_populated_with_graph(self, mock_analyze, make_mode_context):
        mock_analyze.return_value = BranchChanges(
            project_changes={},
            changed_config_files=[ConfigFileChange(path="Directory.Build.props", change_type="M")],
        )
        graph = _make_graph_with_imports(
            {
                "A": ["Directory.Build.props"],
                "B": ["Directory.Build.props"],
                "C": [],
            }
        )
        graph_ctx = MagicMock()
        graph_ctx.graph = graph

        ctx = make_mode_context()
        ctx.graph_ctx = graph_ctx

        result = run_git_analysis(ctx, Path("/tmp/repo"), "feature/x", "main", False)
        assert len(result.props_impacts) == 1
        pi = result.props_impacts[0]
        assert pi.import_path == "Directory.Build.props"
        assert pi.change_type == "M"
        assert sorted(pi.importing_projects) == ["A", "B"]

    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_orphan_props_no_crash(self, mock_analyze, make_mode_context):
        mock_analyze.return_value = BranchChanges(
            project_changes={},
            changed_config_files=[ConfigFileChange(path="orphan.props", change_type="M")],
        )
        graph = _make_graph_with_imports({"A": ["other.props"]})
        graph_ctx = MagicMock()
        graph_ctx.graph = graph

        ctx = make_mode_context()
        ctx.graph_ctx = graph_ctx

        result = run_git_analysis(ctx, Path("/tmp/repo"), "feature/x", "main", False)
        assert len(result.props_impacts) == 1
        assert result.props_impacts[0].importing_projects == []

    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_no_graph_graceful_skip(self, mock_analyze, make_mode_context):
        mock_analyze.return_value = BranchChanges(
            project_changes={},
            changed_config_files=[ConfigFileChange(path="Directory.Build.props", change_type="M")],
        )
        ctx = make_mode_context(no_graph=True)

        result = run_git_analysis(ctx, Path("/tmp/repo"), "feature/x", "main", False)
        assert result.props_impacts == []

    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_no_config_files_skips_index_build(self, mock_analyze, make_mode_context):
        mock_analyze.return_value = BranchChanges(
            project_changes={},
            changed_config_files=[],
        )
        graph_ctx = MagicMock()
        graph_ctx.graph = _make_graph_with_imports({"A": ["some.props"]})

        ctx = make_mode_context()
        ctx.graph_ctx = graph_ctx

        with patch("scatter.analysis._build_import_reverse_index") as mock_idx:
            result = run_git_analysis(ctx, Path("/tmp/repo"), "feature/x", "main", False)
            mock_idx.assert_not_called()
        assert result.props_impacts == []

    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_deleted_props_still_matched(self, mock_analyze, make_mode_context):
        mock_analyze.return_value = BranchChanges(
            project_changes={},
            changed_config_files=[ConfigFileChange(path="Directory.Build.props", change_type="D")],
        )
        graph = _make_graph_with_imports({"X": ["Directory.Build.props"]})
        graph_ctx = MagicMock()
        graph_ctx.graph = graph

        ctx = make_mode_context()
        ctx.graph_ctx = graph_ctx

        result = run_git_analysis(ctx, Path("/tmp/repo"), "feature/x", "main", False)
        assert len(result.props_impacts) == 1
        assert result.props_impacts[0].change_type == "D"
        assert result.props_impacts[0].importing_projects == ["X"]


# ===========================================================================
# TestModeResultBackcompat
# ===========================================================================


class TestModeResultBackcompat:
    def test_defaults_include_empty_props_impacts(self):
        r = ModeResult()
        assert r.props_impacts == []

    def test_without_props_impacts_kwarg(self):
        r = ModeResult(all_results=[], filter_pipeline=None, graph_enriched=False)
        assert r.props_impacts == []
