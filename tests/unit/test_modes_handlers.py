"""Tests for mode handler functions in scatter.modes (graph, impact, target, git, sproc, dump_index)."""

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_args(**overrides):
    defaults = dict(
        branch_name=None,
        target_project=None,
        stored_procedure=None,
        sow=None,
        sow_file=None,
        graph=False,
        dump_index=False,
        output_format="console",
        pipeline_csv=None,
        class_name=None,
        method_name=None,
        verbose=False,
        search_scope=None,
        repo_path=".",
        base_branch="main",
        app_config_path=None,
        summarize_consumers=False,
        enable_hybrid_git=False,
        google_api_key=None,
        max_workers=1,
        chunk_size=75,
        disable_multiprocessing=True,
        cs_analysis_chunk_size=50,
        csproj_analysis_chunk_size=25,
        no_graph=True,
        graph_metrics=False,
        output_file=None,
        target_namespace=None,
        sproc_regex_pattern=None,
        sow_min_confidence=0.5,
        sow_dry_run=False,
        include_graph_topology=False,
        full_type_scan=False,
        gemini_model=None,
        wex_api_key=None,
        wex_model=None,
        max_depth=None,
        max_ai_calls=None,
        parser_mode=None,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def _mock_graph(node_count=5, edge_count=8):
    graph = MagicMock()
    graph.node_count = node_count
    graph.edge_count = edge_count
    return graph


def _graph_mode_ctx(make_mode_context):
    ctx = make_mode_context()
    ctx.config.graph.cache_dir = None
    ctx.config.graph.rebuild = True
    ctx.config.graph.invalidation = MagicMock()
    ctx.config.analysis.parser_mode = "hybrid"
    ctx.config.graph.coupling_weights = {}
    ctx.config.exclude_patterns = []
    ctx.config.db.include_db_edges = False
    ctx.config.db.sproc_prefixes = []
    return ctx


# Patch targets for lazy imports inside run_graph_mode
_GRAPH_PATCHES = {
    "build_graph": "scatter.analyzers.graph_builder.build_dependency_graph",
    "compute_metrics": "scatter.analyzers.coupling_analyzer.compute_all_metrics",
    "detect_cycles": "scatter.analyzers.coupling_analyzer.detect_cycles",
    "rank": "scatter.analyzers.coupling_analyzer.rank_by_coupling",
    "cache_path": "scatter.store.graph_cache.get_default_cache_path",
    "load_cache": "scatter.store.graph_cache.load_and_validate",
    "save_graph": "scatter.store.graph_cache.save_graph",
    "print_report": "scatter.reports.graph_reporter.print_graph_report",
    "json_report": "scatter.reports.graph_reporter.write_graph_json_report",
    "find_clusters": "scatter.analyzers.domain_analyzer.find_clusters",
    "sol_metrics": "scatter.analyzers.coupling_analyzer.compute_solution_metrics",
    "health": "scatter.analyzers.health_analyzer.compute_health_dashboard",
    "pop_solutions": "scatter.modes.setup.populate_graph_solutions",
}


# ===========================================================================
# scatter.modes.graph  — run_graph_mode
# ===========================================================================


class TestRunGraphMode:
    def _run(self, args, ctx, **mock_overrides):
        """Run graph mode with all dependencies mocked."""
        from scatter.modes.graph import run_graph_mode

        graph = mock_overrides.pop("graph", _mock_graph())
        patches = {}
        for key, target in _GRAPH_PATCHES.items():
            patches[key] = patch(target)

        mocks = {k: p.start() for k, p in patches.items()}
        try:
            mocks["build_graph"].return_value = graph
            mocks["load_cache"].return_value = mock_overrides.get("cache_result", None)
            mocks["cache_path"].return_value = Path("/tmp/cache.json")
            mocks["compute_metrics"].return_value = {}
            mocks["detect_cycles"].return_value = []
            mocks["rank"].return_value = []
            mocks["find_clusters"].return_value = []
            mocks["sol_metrics"].return_value = (None, None)

            run_graph_mode(args, ctx, 0.0)
            return mocks
        finally:
            for p in patches.values():
                p.stop()

    def test_console_output(self, make_mode_context):
        args = _fake_args(graph=True, output_format="console")
        ctx = _graph_mode_ctx(make_mode_context)
        mocks = self._run(args, ctx)
        mocks["print_report"].assert_called_once()
        mocks["build_graph"].assert_called_once()

    def test_uses_cached_graph(self, make_mode_context):
        args = _fake_args(graph=True, output_format="console")
        ctx = _graph_mode_ctx(make_mode_context)
        ctx.config.graph.rebuild = False
        cached_graph = _mock_graph(3, 2)
        mocks = self._run(args, ctx, cache_result=(cached_graph, MagicMock()), graph=cached_graph)
        mocks["build_graph"].assert_not_called()

    def test_json_output(self, make_mode_context, tmp_path):
        out = tmp_path / "out.json"
        args = _fake_args(graph=True, output_format="json", output_file=str(out))
        ctx = _graph_mode_ctx(make_mode_context)
        mocks = self._run(args, ctx)
        mocks["json_report"].assert_called_once()

    def test_csv_output(self, make_mode_context, tmp_path):
        out = tmp_path / "out.csv"
        args = _fake_args(graph=True, output_format="csv", output_file=str(out))
        ctx = _graph_mode_ctx(make_mode_context)
        with patch("scatter.reports.graph_reporter.write_graph_csv_report") as mock_csv:
            self._run(args, ctx)
            mock_csv.assert_called_once()

    def test_mermaid_output_to_stdout(self, make_mode_context):
        args = _fake_args(graph=True, output_format="mermaid", output_file=None)
        ctx = _graph_mode_ctx(make_mode_context)
        with patch(
            "scatter.reports.graph_reporter.generate_mermaid", return_value="graph TD"
        ) as mock_merm:
            self._run(args, ctx)
            mock_merm.assert_called_once()

    def test_mermaid_output_to_file(self, make_mode_context, tmp_path):
        out = tmp_path / "out.mmd"
        args = _fake_args(graph=True, output_format="mermaid", output_file=str(out))
        ctx = _graph_mode_ctx(make_mode_context)
        with patch("scatter.reports.graph_reporter.generate_mermaid", return_value="graph TD"):
            self._run(args, ctx)
        assert out.read_text() == "graph TD"

    def test_markdown_to_file(self, make_mode_context, tmp_path):
        out = tmp_path / "out.md"
        args = _fake_args(graph=True, output_format="markdown", output_file=str(out))
        ctx = _graph_mode_ctx(make_mode_context)
        with patch("scatter.reports.markdown_reporter.write_graph_markdown_report") as mock_md:
            self._run(args, ctx)
            mock_md.assert_called_once()

    def test_markdown_to_stdout(self, make_mode_context):
        args = _fake_args(graph=True, output_format="markdown", output_file=None)
        ctx = _graph_mode_ctx(make_mode_context)
        with patch(
            "scatter.reports.markdown_reporter.build_graph_markdown", return_value="# Graph"
        ) as mock_md:
            self._run(args, ctx)
            mock_md.assert_called_once()


# ===========================================================================
# scatter.modes.impact  — run_impact_mode
# ===========================================================================


class TestRunImpactMode:
    def _make_impact_report(self):
        report = MagicMock()
        target = MagicMock()
        target.consumers = [MagicMock()]
        report.targets = [target]
        return report

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    @patch("scatter.reports.console_reporter.print_impact_report")
    def test_console_output(
        self, mock_print_report, mock_analysis, mock_enrich, mock_print, make_mode_context
    ):
        from scatter.modes.impact import run_impact_mode

        report = self._make_impact_report()
        mock_analysis.return_value = report

        args = _fake_args(sow="test change", output_format="console")
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        run_impact_mode(args, ctx, 0.0)
        mock_print_report.assert_called_once_with(report)

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    @patch("scatter.reports.json_reporter.write_impact_json_report")
    def test_json_output(
        self, mock_json, mock_analysis, mock_enrich, mock_print, make_mode_context, tmp_path
    ):
        from scatter.modes.impact import run_impact_mode

        report = self._make_impact_report()
        mock_analysis.return_value = report

        out = tmp_path / "out.json"
        args = _fake_args(sow="test", output_format="json", output_file=str(out))
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        run_impact_mode(args, ctx, 0.0)
        mock_json.assert_called_once()

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    @patch("scatter.reports.csv_reporter.write_impact_csv_report")
    def test_csv_output(
        self, mock_csv, mock_analysis, mock_enrich, mock_print, make_mode_context, tmp_path
    ):
        from scatter.modes.impact import run_impact_mode

        report = self._make_impact_report()
        mock_analysis.return_value = report

        out = tmp_path / "out.csv"
        args = _fake_args(sow="test", output_format="csv", output_file=str(out))
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        run_impact_mode(args, ctx, 0.0)
        mock_csv.assert_called_once()

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    def test_pipelines_output(self, mock_analysis, mock_enrich, mock_print, make_mode_context):
        from scatter.modes.impact import run_impact_mode

        report = self._make_impact_report()
        mock_analysis.return_value = report

        args = _fake_args(sow="test", output_format="pipelines")
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        with patch(
            "scatter.reports.pipeline_reporter.extract_impact_pipeline_names",
            return_value=["pipe-1"],
        ):
            with patch(
                "scatter.reports.pipeline_reporter.format_pipeline_output", return_value="pipe-1"
            ):
                run_impact_mode(args, ctx, 0.0)

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    def test_sow_file_input(
        self, mock_analysis, mock_enrich, mock_print, make_mode_context, tmp_path
    ):
        from scatter.modes.impact import run_impact_mode

        sow_file = tmp_path / "sow.txt"
        sow_file.write_text("change the widget module")

        report = self._make_impact_report()
        mock_analysis.return_value = report

        args = _fake_args(sow=None, sow_file=str(sow_file), output_format="console")
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        with patch("scatter.reports.console_reporter.print_impact_report"):
            run_impact_mode(args, ctx, 0.0)

        call_kwargs = mock_analysis.call_args[1]
        assert call_kwargs["sow_text"] == "change the widget module"

    def test_missing_sow_file_exits(self, make_mode_context):
        from scatter.modes.impact import run_impact_mode

        args = _fake_args(sow=None, sow_file="/no/such/file.txt", output_format="console")
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        with pytest.raises(SystemExit):
            run_impact_mode(args, ctx, 0.0)

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    def test_markdown_to_stdout(self, mock_analysis, mock_enrich, mock_print, make_mode_context):
        from scatter.modes.impact import run_impact_mode

        report = self._make_impact_report()
        mock_analysis.return_value = report

        args = _fake_args(sow="test", output_format="markdown", output_file=None)
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        with patch(
            "scatter.reports.markdown_reporter.build_impact_markdown", return_value="# Impact"
        ) as mock_md:
            run_impact_mode(args, ctx, 0.0)
            mock_md.assert_called_once()

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    def test_markdown_to_file(
        self, mock_analysis, mock_enrich, mock_print, make_mode_context, tmp_path
    ):
        from scatter.modes.impact import run_impact_mode

        report = self._make_impact_report()
        mock_analysis.return_value = report

        out = tmp_path / "out.md"
        args = _fake_args(sow="test", output_format="markdown", output_file=str(out))
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        with patch("scatter.reports.markdown_reporter.write_impact_markdown_report") as mock_md:
            run_impact_mode(args, ctx, 0.0)
            mock_md.assert_called_once()

    @patch("scatter.modes.impact.print")
    @patch("scatter.modes.impact.apply_impact_graph_enrichment")
    @patch("scatter.analyzers.impact_analyzer.run_impact_analysis")
    def test_pipelines_to_file(
        self, mock_analysis, mock_enrich, mock_print, make_mode_context, tmp_path
    ):
        from scatter.modes.impact import run_impact_mode

        report = self._make_impact_report()
        mock_analysis.return_value = report

        out = tmp_path / "out.txt"
        args = _fake_args(sow="test", output_format="pipelines", output_file=str(out))
        ctx = make_mode_context()
        ctx.config.max_depth = 3

        with patch(
            "scatter.reports.pipeline_reporter.extract_impact_pipeline_names", return_value=["p1"]
        ):
            with patch("scatter.reports.pipeline_reporter.write_pipeline_report") as mock_write:
                run_impact_mode(args, ctx, 0.0)
                mock_write.assert_called_once()


# ===========================================================================
# scatter.modes.target — run_target_mode
# ===========================================================================


class TestRunTargetMode:
    @patch("scatter.modes.target.dispatch_legacy_output")
    @patch("scatter.modes.target.run_target_analysis")
    def test_dispatches_csproj_file(
        self, mock_analysis, mock_dispatch, make_mode_context, tmp_path
    ):
        from scatter.modes.target import run_target_mode

        csproj = tmp_path / "Foo.csproj"
        csproj.write_text("<Project/>")

        result = MagicMock()
        mock_analysis.return_value = result

        args = _fake_args(target_project=str(csproj))
        ctx = make_mode_context()

        run_target_mode(args, ctx, 0.0)
        mock_dispatch.assert_called_once()

    @patch("scatter.modes.target.dispatch_legacy_output")
    @patch("scatter.modes.target.run_target_analysis")
    def test_resolves_directory_to_csproj(
        self, mock_analysis, mock_dispatch, make_mode_context, tmp_path
    ):
        from scatter.modes.target import run_target_mode

        csproj = tmp_path / "Foo.csproj"
        csproj.write_text("<Project/>")

        result = MagicMock()
        mock_analysis.return_value = result

        args = _fake_args(target_project=str(tmp_path))
        ctx = make_mode_context()

        run_target_mode(args, ctx, 0.0)
        call_args = mock_analysis.call_args[0]
        assert call_args[1].suffix == ".csproj"

    def test_exits_when_no_csproj_in_dir(self, make_mode_context, tmp_path):
        from scatter.modes.target import run_target_mode

        args = _fake_args(target_project=str(tmp_path))
        ctx = make_mode_context()

        with pytest.raises(SystemExit):
            run_target_mode(args, ctx, 0.0)

    @patch("scatter.modes.target.dispatch_legacy_output")
    @patch("scatter.modes.target.run_target_analysis", side_effect=ValueError("bad"))
    def test_exits_on_value_error(self, mock_analysis, mock_dispatch, make_mode_context, tmp_path):
        from scatter.modes.target import run_target_mode

        csproj = tmp_path / "Foo.csproj"
        csproj.write_text("<Project/>")

        args = _fake_args(target_project=str(csproj))
        ctx = make_mode_context()

        with pytest.raises(SystemExit):
            run_target_mode(args, ctx, 0.0)


# ===========================================================================
# scatter.modes.git — run_git_mode
# ===========================================================================


class TestRunGitMode:
    @patch("scatter.modes.git.dispatch_legacy_output")
    @patch("scatter.modes.git.run_git_analysis")
    def test_dispatches_result(self, mock_analysis, mock_dispatch, make_mode_context):
        from scatter.modes.git import run_git_mode

        result = MagicMock()
        mock_analysis.return_value = result

        args = _fake_args(branch_name="feature/x", base_branch="main", enable_hybrid_git=False)
        ctx = make_mode_context(repo_path=Path("/tmp/repo"))

        run_git_mode(args, ctx, 0.0)
        mock_analysis.assert_called_once()
        mock_dispatch.assert_called_once()

    def test_asserts_repo_path(self, make_mode_context):
        from scatter.modes.git import run_git_mode

        args = _fake_args(branch_name="feature/x", base_branch="main", enable_hybrid_git=False)
        ctx = make_mode_context(repo_path=None)
        ctx.repo_path = None

        with pytest.raises(AssertionError):
            run_git_mode(args, ctx, 0.0)

    @patch("scatter.modes.git.dispatch_legacy_output")
    @patch("scatter.modes.git.run_git_analysis", side_effect=ValueError("bad branch"))
    def test_exits_on_value_error(self, mock_analysis, mock_dispatch, make_mode_context):
        from scatter.modes.git import run_git_mode

        args = _fake_args(branch_name="feature/x", base_branch="main", enable_hybrid_git=False)
        ctx = make_mode_context(repo_path=Path("/tmp/repo"))

        with pytest.raises(SystemExit):
            run_git_mode(args, ctx, 0.0)


# ===========================================================================
# scatter.modes.sproc — run_sproc_mode
# ===========================================================================


class TestRunSprocMode:
    @patch("scatter.modes.sproc.dispatch_legacy_output")
    @patch("scatter.modes.sproc.run_sproc_analysis")
    def test_dispatches_result(self, mock_analysis, mock_dispatch, make_mode_context):
        from scatter.modes.sproc import run_sproc_mode

        result = MagicMock()
        mock_analysis.return_value = result

        args = _fake_args(stored_procedure="dbo.sp_Test", sproc_regex_pattern=None)
        ctx = make_mode_context()

        run_sproc_mode(args, ctx, 0.0)
        mock_analysis.assert_called_once_with(ctx, "dbo.sp_Test", None)
        mock_dispatch.assert_called_once()

    @patch("scatter.modes.sproc.dispatch_legacy_output")
    @patch("scatter.modes.sproc.run_sproc_analysis")
    def test_passes_regex_pattern(self, mock_analysis, mock_dispatch, make_mode_context):
        from scatter.modes.sproc import run_sproc_mode

        result = MagicMock()
        mock_analysis.return_value = result

        args = _fake_args(stored_procedure="dbo.sp_Test", sproc_regex_pattern="sp_.*")
        ctx = make_mode_context()

        run_sproc_mode(args, ctx, 0.0)
        mock_analysis.assert_called_once_with(ctx, "dbo.sp_Test", "sp_.*")


# ===========================================================================
# scatter.modes.dump_index — run_dump_index_mode
# ===========================================================================


class TestRunDumpIndexMode:
    def test_exits_without_search_scope(self):
        from scatter.modes.dump_index import run_dump_index_mode

        args = _fake_args(search_scope=None)
        with pytest.raises(SystemExit):
            run_dump_index_mode(args)

    @patch("scatter.ai.codebase_index.build_codebase_index")
    @patch("scatter.store.graph_cache.save_graph")
    @patch("scatter.modes.dump_index.populate_graph_solutions")
    @patch("scatter.modes.dump_index.build_project_to_solutions", return_value={})
    @patch("scatter.modes.dump_index.scan_solutions", return_value=[])
    @patch("scatter.analyzers.graph_builder.build_dependency_graph")
    @patch("scatter.store.graph_cache.load_and_validate", return_value=None)
    @patch("scatter.store.graph_cache.get_default_cache_path", return_value=Path("/tmp/cache.json"))
    @patch("scatter.config.load_config")
    def test_builds_graph_and_prints_index(
        self,
        mock_config,
        mock_cache_path,
        mock_load,
        mock_build_graph,
        mock_scan_sols,
        mock_build_sols,
        mock_pop,
        mock_save,
        mock_build_index,
        tmp_path,
        capsys,
    ):
        from scatter.modes.dump_index import run_dump_index_mode

        graph = MagicMock()
        mock_build_graph.return_value = graph

        index = MagicMock()
        index.text = "# Codebase Index"
        index.project_count = 5
        index.type_count = 20
        index.sproc_count = 3
        index.file_count = 100
        index.size_bytes = 5000
        mock_build_index.return_value = index

        config = MagicMock()
        config.graph.cache_dir = None
        config.graph.invalidation = MagicMock()
        config.analysis.parser_mode = "hybrid"
        config.exclude_patterns = []
        mock_config.return_value = config

        args = _fake_args(search_scope=str(tmp_path), dump_index=True)
        run_dump_index_mode(args)

        output = capsys.readouterr().out
        assert "Codebase Index" in output
        assert "5 projects" in output

    @patch("scatter.ai.codebase_index.build_codebase_index")
    @patch("scatter.store.graph_cache.load_and_validate")
    @patch("scatter.store.graph_cache.get_default_cache_path", return_value=Path("/tmp/cache.json"))
    @patch("scatter.config.load_config")
    def test_uses_cached_graph(
        self,
        mock_config,
        mock_cache_path,
        mock_load,
        mock_build_index,
        tmp_path,
        capsys,
    ):
        from scatter.modes.dump_index import run_dump_index_mode

        graph = MagicMock()
        mock_load.return_value = (graph, MagicMock())

        index = MagicMock()
        index.text = "# Index"
        index.project_count = 1
        index.type_count = 2
        index.sproc_count = 0
        index.file_count = 5
        index.size_bytes = 100
        mock_build_index.return_value = index

        config = MagicMock()
        config.graph.cache_dir = None
        config.graph.invalidation = MagicMock()
        config.analysis.parser_mode = "hybrid"
        mock_config.return_value = config

        args = _fake_args(search_scope=str(tmp_path), dump_index=True)
        run_dump_index_mode(args)
        mock_build_index.assert_called_once_with(graph, tmp_path.resolve())
