"""Tests for scatter.__main__ — CLI entry point dispatch."""

from argparse import Namespace
from unittest.mock import MagicMock, patch


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


class TestMain:
    @patch("scatter.__main__.run_dump_index_mode")
    @patch("scatter.__main__.build_parser")
    def test_dump_index_dispatches(self, mock_parser, mock_dump):
        args = _fake_args(dump_index=True)
        mock_parser.return_value.parse_args.return_value = args

        from scatter.__main__ import main

        main()
        mock_dump.assert_called_once_with(args)

    @patch("scatter.__main__.run_git_mode")
    @patch("scatter.__main__.build_mode_context")
    @patch("scatter.__main__.build_graph_context_if_needed", return_value=(None, False))
    @patch("scatter.__main__.load_pipeline_csv", return_value={})
    @patch("scatter.__main__.load_batch_jobs", return_value={})
    @patch("scatter.__main__.scan_solutions_data")
    @patch("scatter.__main__.setup_ai_provider", return_value=(None, None))
    @patch("scatter.__main__.load_config_from_args")
    @patch("scatter.__main__.resolve_paths")
    @patch("scatter.__main__.validate_mode_and_format")
    @patch("scatter.__main__.setup_logging")
    @patch("scatter.__main__.build_parser")
    def test_git_mode_dispatches(
        self,
        mock_parser,
        mock_logging,
        mock_validate,
        mock_resolve,
        mock_config,
        mock_ai,
        mock_solutions,
        mock_batch,
        mock_pipeline,
        mock_graph_ctx,
        mock_build_ctx,
        mock_git,
    ):
        args = _fake_args(branch_name="feature/x")
        mock_parser.return_value.parse_args.return_value = args
        mock_resolve.return_value = MagicMock()
        mock_solutions.return_value = MagicMock()
        mock_build_ctx.return_value = MagicMock()

        from scatter.__main__ import main

        main()
        mock_git.assert_called_once()

    @patch("scatter.__main__.run_target_mode")
    @patch("scatter.__main__.build_mode_context")
    @patch("scatter.__main__.build_graph_context_if_needed", return_value=(None, False))
    @patch("scatter.__main__.load_pipeline_csv", return_value={})
    @patch("scatter.__main__.load_batch_jobs", return_value={})
    @patch("scatter.__main__.scan_solutions_data")
    @patch("scatter.__main__.setup_ai_provider", return_value=(None, None))
    @patch("scatter.__main__.load_config_from_args")
    @patch("scatter.__main__.resolve_paths")
    @patch("scatter.__main__.validate_mode_and_format")
    @patch("scatter.__main__.setup_logging")
    @patch("scatter.__main__.build_parser")
    def test_target_mode_dispatches(
        self,
        mock_parser,
        mock_logging,
        mock_validate,
        mock_resolve,
        mock_config,
        mock_ai,
        mock_solutions,
        mock_batch,
        mock_pipeline,
        mock_graph_ctx,
        mock_build_ctx,
        mock_target,
    ):
        args = _fake_args(target_project="Foo.csproj")
        mock_parser.return_value.parse_args.return_value = args
        mock_resolve.return_value = MagicMock()
        mock_solutions.return_value = MagicMock()
        mock_build_ctx.return_value = MagicMock()

        from scatter.__main__ import main

        main()
        mock_target.assert_called_once()

    @patch("scatter.__main__.run_sproc_mode")
    @patch("scatter.__main__.build_mode_context")
    @patch("scatter.__main__.build_graph_context_if_needed", return_value=(None, False))
    @patch("scatter.__main__.load_pipeline_csv", return_value={})
    @patch("scatter.__main__.load_batch_jobs", return_value={})
    @patch("scatter.__main__.scan_solutions_data")
    @patch("scatter.__main__.setup_ai_provider", return_value=(None, None))
    @patch("scatter.__main__.load_config_from_args")
    @patch("scatter.__main__.resolve_paths")
    @patch("scatter.__main__.validate_mode_and_format")
    @patch("scatter.__main__.setup_logging")
    @patch("scatter.__main__.build_parser")
    def test_sproc_mode_dispatches(
        self,
        mock_parser,
        mock_logging,
        mock_validate,
        mock_resolve,
        mock_config,
        mock_ai,
        mock_solutions,
        mock_batch,
        mock_pipeline,
        mock_graph_ctx,
        mock_build_ctx,
        mock_sproc,
    ):
        args = _fake_args(stored_procedure="dbo.sp_Test")
        mock_parser.return_value.parse_args.return_value = args
        mock_resolve.return_value = MagicMock()
        mock_solutions.return_value = MagicMock()
        mock_build_ctx.return_value = MagicMock()

        from scatter.__main__ import main

        main()
        mock_sproc.assert_called_once()

    @patch("scatter.__main__.run_impact_mode")
    @patch("scatter.__main__.build_mode_context")
    @patch("scatter.__main__.build_graph_context_if_needed", return_value=(None, False))
    @patch("scatter.__main__.load_pipeline_csv", return_value={})
    @patch("scatter.__main__.load_batch_jobs", return_value={})
    @patch("scatter.__main__.scan_solutions_data")
    @patch("scatter.__main__.setup_ai_provider", return_value=(None, None))
    @patch("scatter.__main__.load_config_from_args")
    @patch("scatter.__main__.resolve_paths")
    @patch("scatter.__main__.validate_mode_and_format")
    @patch("scatter.__main__.setup_logging")
    @patch("scatter.__main__.build_parser")
    def test_impact_mode_dispatches(
        self,
        mock_parser,
        mock_logging,
        mock_validate,
        mock_resolve,
        mock_config,
        mock_ai,
        mock_solutions,
        mock_batch,
        mock_pipeline,
        mock_graph_ctx,
        mock_build_ctx,
        mock_impact,
    ):
        args = _fake_args(sow="change something")
        mock_parser.return_value.parse_args.return_value = args
        mock_resolve.return_value = MagicMock()
        mock_solutions.return_value = MagicMock()
        mock_build_ctx.return_value = MagicMock()

        from scatter.__main__ import main

        main()
        mock_impact.assert_called_once()

    @patch("scatter.__main__.run_graph_mode")
    @patch("scatter.__main__.build_mode_context")
    @patch("scatter.__main__.build_graph_context_if_needed", return_value=(None, False))
    @patch("scatter.__main__.load_pipeline_csv", return_value={})
    @patch("scatter.__main__.load_batch_jobs", return_value={})
    @patch("scatter.__main__.scan_solutions_data")
    @patch("scatter.__main__.setup_ai_provider", return_value=(None, None))
    @patch("scatter.__main__.load_config_from_args")
    @patch("scatter.__main__.resolve_paths")
    @patch("scatter.__main__.validate_mode_and_format")
    @patch("scatter.__main__.setup_logging")
    @patch("scatter.__main__.build_parser")
    def test_graph_mode_dispatches(
        self,
        mock_parser,
        mock_logging,
        mock_validate,
        mock_resolve,
        mock_config,
        mock_ai,
        mock_solutions,
        mock_batch,
        mock_pipeline,
        mock_graph_ctx,
        mock_build_ctx,
        mock_graph,
    ):
        args = _fake_args(graph=True)
        mock_parser.return_value.parse_args.return_value = args
        mock_resolve.return_value = MagicMock()
        mock_solutions.return_value = MagicMock()
        mock_build_ctx.return_value = MagicMock()

        from scatter.__main__ import main

        main()
        mock_graph.assert_called_once()
