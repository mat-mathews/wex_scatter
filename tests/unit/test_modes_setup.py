"""Tests for scatter.modes.setup — shared setup helpers."""

import csv
import logging
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scatter.modes.setup import (
    ResolvedPaths,
    SolutionData,
    build_graph_context_if_needed,
    build_mode_context,
    load_batch_jobs,
    load_config_from_args,
    load_pipeline_csv,
    populate_graph_solutions,
    resolve_paths,
    scan_solutions_data,
    setup_ai_provider,
    setup_logging,
    validate_mode_and_format,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_args(**overrides):
    """Build a minimal args namespace with sensible defaults."""
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


class _FakeParser:
    """Minimal parser stub that turns parser.error() into SystemExit."""

    def error(self, msg):
        raise SystemExit(msg)


# ---------------------------------------------------------------------------
# populate_graph_solutions
# ---------------------------------------------------------------------------


class TestPopulateGraphSolutions:
    def test_sets_solutions_from_index(self):
        node = MagicMock()
        node.name = "Foo"
        node.solutions = []
        graph = MagicMock()
        graph.get_all_nodes.return_value = [node]

        si = MagicMock()
        si.name = "MySolution"
        solution_index = {"Foo": [si]}

        populate_graph_solutions(graph, solution_index)
        assert node.solutions == ["MySolution"]

    def test_noop_with_empty_index(self):
        graph = MagicMock()
        populate_graph_solutions(graph, {})
        graph.get_all_nodes.assert_not_called()

    def test_noop_with_none_index(self):
        graph = MagicMock()
        populate_graph_solutions(graph, None)
        graph.get_all_nodes.assert_not_called()

    def test_deduplicates_solutions(self):
        node = MagicMock()
        node.name = "Foo"
        node.solutions = []
        graph = MagicMock()
        graph.get_all_nodes.return_value = [node]

        si1 = MagicMock()
        si1.name = "A"
        si2 = MagicMock()
        si2.name = "A"
        solution_index = {"Foo": [si1, si2]}

        populate_graph_solutions(graph, solution_index)
        assert node.solutions == ["A"]


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_verbose_calls_basic_config_with_debug(self):
        args = _fake_args(verbose=True)
        with patch("scatter.modes.setup.logging.basicConfig") as mock_bc:
            setup_logging(args)
            mock_bc.assert_called_once()
            assert mock_bc.call_args[1]["level"] == logging.DEBUG

    def test_non_verbose_calls_basic_config_with_info(self):
        args = _fake_args(verbose=False)
        with patch("scatter.modes.setup.logging.basicConfig") as mock_bc:
            setup_logging(args)
            mock_bc.assert_called_once()
            assert mock_bc.call_args[1]["level"] == logging.INFO


# ---------------------------------------------------------------------------
# validate_mode_and_format
# ---------------------------------------------------------------------------


class TestValidateModeAndFormat:
    def test_no_mode_selected_exits(self):
        args = _fake_args()
        with pytest.raises(SystemExit):
            validate_mode_and_format(args, _FakeParser())

    def test_graph_with_pipelines_format_exits(self):
        args = _fake_args(graph=True, output_format="pipelines")
        with pytest.raises(SystemExit):
            validate_mode_and_format(args, _FakeParser())

    def test_mermaid_without_graph_exits(self):
        args = _fake_args(target_project="Foo.csproj", output_format="mermaid")
        with pytest.raises(SystemExit):
            validate_mode_and_format(args, _FakeParser())

    def test_pipelines_without_csv_warns(self, caplog):
        args = _fake_args(target_project="Foo.csproj", output_format="pipelines")
        with caplog.at_level(logging.WARNING):
            validate_mode_and_format(args, _FakeParser())
        assert "without --pipeline-csv" in caplog.text

    def test_method_without_class_clears_method(self, caplog):
        args = _fake_args(target_project="Foo.csproj", method_name="DoStuff")
        with caplog.at_level(logging.WARNING):
            validate_mode_and_format(args, _FakeParser())
        assert args.method_name is None
        assert "Ignoring --method-name" in caplog.text

    def test_valid_graph_mode_passes(self):
        args = _fake_args(graph=True, output_format="json")
        validate_mode_and_format(args, _FakeParser())  # should not raise

    def test_valid_target_mode_passes(self):
        args = _fake_args(target_project="Foo.csproj")
        validate_mode_and_format(args, _FakeParser())

    def test_mermaid_with_graph_passes(self):
        args = _fake_args(graph=True, output_format="mermaid")
        validate_mode_and_format(args, _FakeParser())


# ---------------------------------------------------------------------------
# resolve_paths
# ---------------------------------------------------------------------------


class TestResolvePaths:
    def test_search_scope_resolved(self, tmp_path):
        args = _fake_args(branch_name="feature/x", search_scope=str(tmp_path))
        result = resolve_paths(args, _FakeParser())
        assert result.search_scope == tmp_path.resolve()

    def test_git_mode_uses_repo_path(self, tmp_path):
        args = _fake_args(branch_name="feature/x", repo_path=str(tmp_path))
        result = resolve_paths(args, _FakeParser())
        assert result.repo_path == tmp_path.resolve()
        assert result.search_scope == tmp_path.resolve()

    def test_sproc_without_search_scope_exits(self):
        args = _fake_args(stored_procedure="dbo.sp_Test")
        with pytest.raises(SystemExit):
            resolve_paths(args, _FakeParser())

    def test_target_without_search_scope_exits(self):
        args = _fake_args(target_project="Foo.csproj")
        with pytest.raises(SystemExit):
            resolve_paths(args, _FakeParser())

    def test_impact_without_search_scope_exits(self):
        args = _fake_args(sow="change something")
        with pytest.raises(SystemExit):
            resolve_paths(args, _FakeParser())

    def test_graph_without_search_scope_exits(self):
        args = _fake_args(graph=True)
        with pytest.raises(SystemExit):
            resolve_paths(args, _FakeParser())

    def test_target_dir_with_csproj(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text("<Project/>")
        args = _fake_args(
            target_project=str(tmp_path),
            search_scope=str(tmp_path),
        )
        result = resolve_paths(args, _FakeParser())
        assert result.search_scope == tmp_path.resolve()

    def test_target_dir_without_csproj_exits(self, tmp_path):
        args = _fake_args(
            target_project=str(tmp_path),
            search_scope=str(tmp_path),
        )
        with pytest.raises(SystemExit):
            resolve_paths(args, _FakeParser())

    def test_target_invalid_file_exits(self, tmp_path):
        bad = tmp_path / "not_a_csproj.txt"
        bad.write_text("hello")
        args = _fake_args(
            target_project=str(bad),
            search_scope=str(tmp_path),
        )
        with pytest.raises(SystemExit):
            resolve_paths(args, _FakeParser())

    def test_pipeline_csv_resolved(self, tmp_path):
        csv_file = tmp_path / "map.csv"
        csv_file.write_text("a,b")
        args = _fake_args(
            branch_name="feature/x",
            search_scope=str(tmp_path),
            pipeline_csv=str(csv_file),
        )
        result = resolve_paths(args, _FakeParser())
        assert result.pipeline_csv == csv_file.resolve()


# ---------------------------------------------------------------------------
# load_config_from_args
# ---------------------------------------------------------------------------


class TestLoadConfigFromArgs:
    @patch("scatter.modes.setup.load_config")
    @patch("scatter.modes.setup._build_cli_overrides", return_value={})
    def test_delegates_to_load_config(self, mock_cli, mock_load):
        paths = ResolvedPaths(search_scope=Path("/tmp"))
        args = _fake_args()
        load_config_from_args(args, paths)
        mock_load.assert_called_once_with(repo_root=Path("/tmp"), cli_overrides={})


# ---------------------------------------------------------------------------
# setup_ai_provider
# ---------------------------------------------------------------------------


class TestSetupAiProvider:
    def test_no_ai_returns_none(self):
        args = _fake_args()
        config = MagicMock()
        provider, budget = setup_ai_provider(args, config)
        assert provider is None
        assert budget is None

    @patch("scatter.ai.router.AIRouter.get_provider")
    def test_summarize_enables_ai(self, mock_get):
        mock_get.return_value = MagicMock()
        args = _fake_args(summarize_consumers=True)
        config = MagicMock()
        config.ai.max_ai_calls = 10
        provider, budget = setup_ai_provider(args, config)
        assert provider is not None
        assert budget is not None

    @patch("scatter.ai.router.AIRouter.get_provider", return_value=None)
    def test_failed_provider_disables_summarize(self, mock_get):
        args = _fake_args(summarize_consumers=True)
        config = MagicMock()
        config.ai.max_ai_calls = None
        setup_ai_provider(args, config)
        assert args.summarize_consumers is False

    @patch("scatter.ai.router.AIRouter.get_provider", return_value=None)
    def test_failed_provider_disables_hybrid_git(self, mock_get):
        args = _fake_args(enable_hybrid_git=True)
        config = MagicMock()
        config.ai.max_ai_calls = None
        setup_ai_provider(args, config)
        assert args.enable_hybrid_git is False

    @patch("scatter.ai.router.AIRouter.get_provider", return_value=None)
    def test_failed_provider_exits_impact_mode(self, mock_get):
        args = _fake_args(sow="test sow")
        config = MagicMock()
        config.ai.max_ai_calls = None
        with pytest.raises(SystemExit):
            setup_ai_provider(args, config)

    @patch("scatter.ai.router.AIRouter.get_provider")
    def test_hybrid_git_enables_ai(self, mock_get):
        mock_get.return_value = MagicMock()
        args = _fake_args(enable_hybrid_git=True)
        config = MagicMock()
        config.ai.max_ai_calls = None
        provider, budget = setup_ai_provider(args, config)
        assert provider is not None

    @patch("scatter.ai.router.AIRouter.get_provider")
    def test_impact_mode_enables_ai(self, mock_get):
        mock_get.return_value = MagicMock()
        args = _fake_args(sow="change the widget")
        config = MagicMock()
        config.ai.max_ai_calls = 5
        provider, budget = setup_ai_provider(args, config)
        assert provider is not None
        assert budget.max_calls == 5


# ---------------------------------------------------------------------------
# scan_solutions_data
# ---------------------------------------------------------------------------


class TestScanSolutionsData:
    @patch("scatter.modes.setup.build_project_to_solutions", return_value={})
    @patch("scatter.modes.setup.scan_solutions")
    def test_returns_solution_data(self, mock_scan, mock_build, tmp_path):
        si = MagicMock()
        si.path = tmp_path / "Foo.sln"
        mock_scan.return_value = [si]

        result = scan_solutions_data(tmp_path)
        assert isinstance(result, SolutionData)
        assert result.infos == [si]
        assert result.file_cache == [si.path]

    @patch("scatter.modes.setup.scan_solutions", side_effect=Exception("boom"))
    def test_handles_scan_error(self, mock_scan, tmp_path):
        result = scan_solutions_data(tmp_path)
        assert result.infos == []
        assert result.file_cache == []


# ---------------------------------------------------------------------------
# load_batch_jobs
# ---------------------------------------------------------------------------


class TestLoadBatchJobs:
    def test_no_config_path_returns_empty(self):
        args = _fake_args()
        assert load_batch_jobs(args) == {}

    @patch("scatter.compat.v1_bridge.map_batch_jobs_from_config_repo", return_value={"pipe": ["j1"]})
    def test_loads_from_path(self, mock_map, tmp_path):
        args = _fake_args(app_config_path=str(tmp_path))
        result = load_batch_jobs(args)
        assert result == {"pipe": ["j1"]}

    def test_nonexistent_path_returns_empty(self):
        args = _fake_args(app_config_path="/no/such/path")
        result = load_batch_jobs(args)
        assert result == {}


# ---------------------------------------------------------------------------
# load_pipeline_csv
# ---------------------------------------------------------------------------


class TestLoadPipelineCsv:
    def test_no_csv_returns_empty(self):
        assert load_pipeline_csv(None) == {}

    def test_missing_file_returns_empty(self, tmp_path):
        result = load_pipeline_csv(tmp_path / "nope.csv")
        assert result == {}

    def test_loads_valid_csv(self, tmp_path):
        csv_file = tmp_path / "pipe.csv"
        csv_file.write_text(
            "Application Name,Pipeline Name\nFoo,pipe-foo\nBar,pipe-bar\n"
        )
        result = load_pipeline_csv(csv_file)
        assert result == {"Foo": "pipe-foo", "Bar": "pipe-bar"}

    def test_missing_columns_returns_empty(self, tmp_path):
        csv_file = tmp_path / "pipe.csv"
        csv_file.write_text("Name,Value\nFoo,1\n")
        result = load_pipeline_csv(csv_file)
        assert result == {}

    def test_duplicate_apps_last_wins(self, tmp_path):
        csv_file = tmp_path / "pipe.csv"
        csv_file.write_text(
            "Application Name,Pipeline Name\nFoo,pipe-1\nFoo,pipe-2\n"
        )
        result = load_pipeline_csv(csv_file)
        assert result == {"Foo": "pipe-2"}

    def test_skips_blank_rows(self, tmp_path):
        csv_file = tmp_path / "pipe.csv"
        csv_file.write_text(
            "Application Name,Pipeline Name\nFoo,pipe-foo\n,\n"
        )
        result = load_pipeline_csv(csv_file)
        assert result == {"Foo": "pipe-foo"}


# ---------------------------------------------------------------------------
# build_graph_context_if_needed
# ---------------------------------------------------------------------------


class TestBuildGraphContextIfNeeded:
    def test_skipped_when_no_graph_flag(self):
        args = _fake_args(no_graph=True)
        ctx, enriched = build_graph_context_if_needed(args, MagicMock(), Path("/tmp"), {})
        assert ctx is None
        assert enriched is False

    def test_skipped_in_graph_mode(self):
        args = _fake_args(no_graph=False, graph=True)
        ctx, enriched = build_graph_context_if_needed(args, MagicMock(), Path("/tmp"), {})
        assert ctx is None
        assert enriched is False

    @patch("scatter.analyzers.graph_enrichment.build_graph_context", return_value=MagicMock())
    @patch("scatter.store.graph_cache.cache_exists", return_value=True)
    def test_builds_when_cache_exists(self, mock_cache, mock_build):
        args = _fake_args(no_graph=False, graph=False, graph_metrics=False)
        config = MagicMock()
        ctx, enriched = build_graph_context_if_needed(args, config, Path("/tmp"), {})
        assert ctx is not None
        assert enriched is True

    @patch("scatter.analyzers.graph_enrichment.build_graph_context", return_value=None)
    @patch("scatter.store.graph_cache.cache_exists", return_value=False)
    def test_graph_metrics_requested_but_unavailable(self, mock_cache, mock_build, caplog):
        args = _fake_args(no_graph=False, graph=False, graph_metrics=True)
        config = MagicMock()
        with caplog.at_level(logging.WARNING):
            ctx, enriched = build_graph_context_if_needed(args, config, Path("/tmp"), {})
        assert ctx is None
        assert enriched is False
        assert "unavailable" in caplog.text.lower()


# ---------------------------------------------------------------------------
# build_mode_context
# ---------------------------------------------------------------------------


class TestBuildModeContext:
    def test_assembles_context(self, make_mode_context):
        args = _fake_args(target_project="Foo.csproj", search_scope="/tmp/scope")
        paths = ResolvedPaths(search_scope=Path("/tmp/scope"))
        config = MagicMock()
        solutions = SolutionData(infos=[], index={}, file_cache=[])

        ctx = build_mode_context(
            args, paths, config, None, solutions, {}, {}, None, False,
        )
        assert ctx.search_scope == Path("/tmp/scope")
        assert ctx.disable_multiprocessing is True
        assert ctx.no_graph is True
