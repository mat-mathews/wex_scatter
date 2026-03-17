"""Smoke tests for scatter.cli.dispatch_legacy_output."""
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from scatter.cli import dispatch_legacy_output, _build_metadata, _require_output_file


def _fake_args(**overrides):
    """Build a minimal args namespace for dispatch testing."""
    defaults = dict(
        output_format="console",
        output_file=None,
        verbose=False,
        google_api_key=None,
        graph_metrics=False,
        no_graph=False,
        branch_name=None,
        target_project=None,
        stored_procedure=None,
        sow=None,
        sow_file=None,
        graph=False,
        repo_path=".",
        base_branch="main",
        search_scope="/tmp",
        pipeline_csv=None,
        class_name=None,
        method_name=None,
        target_namespace=None,
        max_workers=4,
        chunk_size=75,
        disable_multiprocessing=False,
        cs_analysis_chunk_size=50,
        csproj_analysis_chunk_size=25,
        summarize_consumers=False,
        gemini_model=None,
        enable_hybrid_git=False,
        app_config_path=None,
        rebuild_graph=False,
        include_db=False,
        include_graph_topology=False,
        max_depth=None,
        sproc_regex_pattern=None,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class TestDispatchLegacyOutput:

    @patch("scatter.cli.print_console_report")
    def test_console_format(self, mock_console):
        args = _fake_args(output_format="console")
        results = [{"TargetProjectName": "A", "TriggeringType": "T", "ConsumerProjectName": "C"}]
        dispatch_legacy_output(results, None, args, Path("/tmp"), 0.0, False)
        mock_console.assert_called_once()

    @patch("scatter.cli.write_json_report")
    @patch("scatter.cli.prepare_detailed_results")
    def test_json_format(self, mock_prepare, mock_write, tmp_path):
        out = tmp_path / "out.json"
        args = _fake_args(output_format="json", output_file=str(out))
        mock_prepare.return_value = []
        dispatch_legacy_output([], None, args, Path("/tmp"), 0.0, False)
        mock_write.assert_called_once()

    @patch("scatter.cli.write_csv_report")
    @patch("scatter.cli.prepare_detailed_results")
    def test_csv_format(self, mock_prepare, mock_write, tmp_path):
        out = tmp_path / "out.csv"
        args = _fake_args(output_format="csv", output_file=str(out))
        mock_prepare.return_value = []
        dispatch_legacy_output([], None, args, Path("/tmp"), 0.0, False)
        mock_write.assert_called_once()

    def test_empty_results_no_crash(self):
        args = _fake_args(output_format="console")
        # Should not raise
        with patch("scatter.cli.print_console_report"):
            dispatch_legacy_output([], None, args, Path("/tmp"), 0.0, False)

    @patch("scatter.reports.markdown_reporter.write_markdown_report")
    @patch("scatter.cli.prepare_detailed_results")
    def test_markdown_format_to_file(self, mock_prepare, mock_write, tmp_path):
        out = tmp_path / "out.md"
        args = _fake_args(output_format="markdown", output_file=str(out))
        mock_prepare.return_value = []
        dispatch_legacy_output([], None, args, Path("/tmp"), 0.0, False)
        mock_write.assert_called_once()

    @patch("scatter.reports.markdown_reporter.build_markdown", return_value="# Report")
    @patch("scatter.cli.prepare_detailed_results")
    def test_markdown_format_to_stdout(self, mock_prepare, mock_md, capsys):
        args = _fake_args(output_format="markdown", output_file=None)
        mock_prepare.return_value = []
        dispatch_legacy_output([], None, args, Path("/tmp"), 0.0, False)
        mock_md.assert_called_once()
        captured = capsys.readouterr()
        assert "# Report" in captured.out

    @patch("scatter.reports.pipeline_reporter.extract_pipeline_names", return_value=["pipe-a"])
    @patch("scatter.reports.pipeline_reporter.format_pipeline_output", return_value="pipe-a")
    def test_pipelines_format_to_stdout(self, mock_format, mock_extract, capsys):
        args = _fake_args(output_format="pipelines", output_file=None)
        results = [{"TargetProjectName": "A"}]
        dispatch_legacy_output(results, None, args, Path("/tmp"), 0.0, False)
        mock_extract.assert_called_once()
        captured = capsys.readouterr()
        assert "pipe-a" in captured.out

    @patch("scatter.reports.pipeline_reporter.extract_pipeline_names", return_value=["pipe-a"])
    @patch("scatter.reports.pipeline_reporter.write_pipeline_report")
    def test_pipelines_format_to_file(self, mock_write, mock_extract, tmp_path):
        out = tmp_path / "pipes.txt"
        args = _fake_args(output_format="pipelines", output_file=str(out))
        results = [{"TargetProjectName": "A"}]
        dispatch_legacy_output(results, None, args, Path("/tmp"), 0.0, False)
        mock_write.assert_called_once()

    def test_results_are_sorted(self):
        args = _fake_args(output_format="console")
        results = [
            {"TargetProjectName": "B", "TriggeringType": "T", "ConsumerProjectName": "Z"},
            {"TargetProjectName": "A", "TriggeringType": "T", "ConsumerProjectName": "Y"},
        ]
        with patch("scatter.cli.print_console_report"):
            dispatch_legacy_output(results, None, args, Path("/tmp"), 0.0, False)
        assert results[0]["TargetProjectName"] == "A"
        assert results[1]["TargetProjectName"] == "B"


class TestBuildMetadata:

    def test_metadata_has_expected_keys(self):
        args = _fake_args()
        meta = _build_metadata(args, Path("/tmp"), 0.0, graph_enriched=True)
        assert "scatter_version" in meta
        assert "timestamp" in meta
        assert "cli_args" in meta
        assert "search_scope" in meta
        assert "duration_seconds" in meta
        assert meta["graph_enriched"] is True

    def test_metadata_redacts_api_key(self):
        args = _fake_args(google_api_key="secret")
        meta = _build_metadata(args, Path("/tmp"), 0.0)
        assert "google_api_key" not in meta["cli_args"]


class TestRequireOutputFile:

    def test_exits_when_missing(self):
        args = _fake_args(output_file=None)
        with pytest.raises(SystemExit):
            _require_output_file(args, "JSON")

    def test_returns_path_when_present(self):
        args = _fake_args(output_file="/tmp/out.json")
        result = _require_output_file(args, "JSON")
        assert result == Path("/tmp/out.json")
