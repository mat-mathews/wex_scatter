"""Tests for Initiative 6 Phase 1: Report Quality Fixes."""

import argparse
import csv
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scatter.reports.json_reporter import (
    prepare_detailed_results,
    write_json_report,
    write_impact_json_report,
)
from scatter.reports.console_reporter import print_console_report
from scatter.reports.csv_reporter import write_csv_report, write_impact_csv_report
from scatter.reports.graph_reporter import build_graph_json
from scatter.core.models import (
    AnalysisTarget,
    ConsumerResult,
    EnrichedConsumer,
    TargetImpact,
    ImpactReport,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_result(**overrides):
    """Build a single ConsumerResult with sane defaults."""
    # Map PascalCase override keys to snake_case for backward compat with test call sites
    _KEY_MAP = {
        "TargetProjectName": "target_project_name",
        "TargetProjectPath": "target_project_path",
        "TriggeringType": "triggering_type",
        "ConsumerProjectName": "consumer_project_name",
        "ConsumerProjectPath": "consumer_project_path",
        "ConsumingSolutions": "consuming_solutions",
        "PipelineName": "pipeline_name",
        "BatchJobVerification": "batch_job_verification",
        "ConsumerFileSummaries": "consumer_file_summaries",
    }
    defaults = dict(
        target_project_name="Lib.Core",
        target_project_path="src/Lib.Core/Lib.Core.csproj",
        triggering_type="MyClass",
        consumer_project_name="App.Web",
        consumer_project_path="src/App.Web/App.Web.csproj",
        consuming_solutions=["Sol1.sln", "Sol2.sln"],
        pipeline_name="my-pipeline",
        batch_job_verification="Verified",
        consumer_file_summaries={"Startup.cs": "Registers DI."},
    )
    for k, v in overrides.items():
        defaults[_KEY_MAP.get(k, k)] = v
    return ConsumerResult(**defaults)


def _make_impact_report(solutions=None, coupling_vectors=None):
    """Build a minimal ImpactReport for testing."""
    consumer = EnrichedConsumer(
        consumer_path=Path("src/App.Web/App.Web.csproj"),
        consumer_name="App.Web",
        solutions=solutions or ["Sol1.sln", "Sol2.sln"],
        pipeline_name="my-pipeline",
        depth=0,
        confidence=0.9,
        confidence_label="HIGH",
        coupling_vectors=coupling_vectors or ["namespace", "project-ref"],
    )
    target = TargetImpact(
        target=AnalysisTarget(target_type="project", name="Lib.Core"),
        consumers=[consumer],
        total_direct=1,
        total_transitive=0,
    )
    return ImpactReport(sow_text="Test SOW", targets=[target])


SAMPLE_METADATA = {
    "scatter_version": "2.1.0",
    "timestamp": "2026-03-10T00:00:00+00:00",
    "cli_args": {"target_project": "x"},
    "search_scope": "/repo",
    "duration_seconds": 1.23,
}


# ── 1a: JSON Serialization Fixes ────────────────────────────────────


class TestJsonSerializationFixes:
    """Verify prepare_detailed_results preserves native types."""

    def test_consuming_solutions_stays_list(self):
        results = prepare_detailed_results([_make_result()])
        assert isinstance(results[0]["ConsumingSolutions"], list)

    def test_consumer_file_summaries_stays_dict(self):
        results = prepare_detailed_results([_make_result()])
        assert isinstance(results[0]["ConsumerFileSummaries"], dict)

    def test_empty_pipeline_becomes_none(self):
        results = prepare_detailed_results([_make_result(PipelineName="")])
        assert results[0]["PipelineName"] is None

    def test_empty_batch_verification_becomes_none(self):
        results = prepare_detailed_results([_make_result(BatchJobVerification="")])
        assert results[0]["BatchJobVerification"] is None

    def test_populated_pipeline_preserved(self):
        results = prepare_detailed_results([_make_result(PipelineName="deploy-prod")])
        assert results[0]["PipelineName"] == "deploy-prod"

    def test_json_roundtrip_native_types(self):
        """Full JSON serialization preserves list/dict types."""
        results = prepare_detailed_results([_make_result()])
        serialized = json.dumps(results)
        parsed = json.loads(serialized)
        assert isinstance(parsed[0]["ConsumingSolutions"], list)
        assert isinstance(parsed[0]["ConsumerFileSummaries"], dict)


# ── 1b: Report Metadata ─────────────────────────────────────────────


class TestMetadata:
    """Verify metadata inclusion/omission in JSON reports."""

    def test_legacy_json_includes_metadata(self, tmp_path):
        buf = tmp_path / "legacy.json"
        results = prepare_detailed_results([_make_result()])
        write_json_report(results, buf, metadata=SAMPLE_METADATA)
        data = json.loads(buf.read_text())
        assert "metadata" in data
        assert data["metadata"]["scatter_version"] == "2.1.0"

    def test_legacy_json_omits_metadata_when_none(self, tmp_path):
        buf = tmp_path / "legacy_no_meta.json"
        results = prepare_detailed_results([_make_result()])
        write_json_report(results, buf)
        data = json.loads(buf.read_text())
        assert "metadata" not in data

    def test_impact_json_includes_metadata(self, tmp_path):
        buf = tmp_path / "impact.json"
        report = _make_impact_report()
        write_impact_json_report(report, buf, metadata=SAMPLE_METADATA)
        data = json.loads(buf.read_text())
        assert "metadata" in data
        assert set(data["metadata"].keys()) == {
            "scatter_version",
            "timestamp",
            "cli_args",
            "search_scope",
            "duration_seconds",
        }

    def test_graph_json_includes_metadata(self):
        """build_graph_json includes metadata when provided."""
        from scatter.core.graph import DependencyGraph

        graph = DependencyGraph()
        result = build_graph_json(graph, {}, [], [], metadata=SAMPLE_METADATA)
        assert "metadata" in result
        assert result["metadata"]["scatter_version"] == "2.1.0"

    def test_graph_json_omits_metadata_when_none(self):
        from scatter.core.graph import DependencyGraph

        graph = DependencyGraph()
        result = build_graph_json(graph, {}, [], [])
        assert "metadata" not in result

    def test_empty_metadata_dict_still_included(self, tmp_path):
        """An empty metadata dict {} should still appear in the output."""
        buf = tmp_path / "empty_meta.json"
        results = prepare_detailed_results([_make_result()])
        write_json_report(results, buf, metadata={})
        data = json.loads(buf.read_text())
        assert "metadata" in data
        assert data["metadata"] == {}


# ── 1c: Console Polish ──────────────────────────────────────────────


class TestConsolePolish:
    """Verify console formatting improvements."""

    def _capture_console(self, results, graph_metrics_requested=False):
        """Run print_console_report and capture stdout."""
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            print_console_report(results, graph_metrics_requested=graph_metrics_requested)
            return mock_out.getvalue()

    def test_na_type_suppressed(self):
        output = self._capture_console([_make_result(TriggeringType="N/A (Project Reference)")])
        assert "Triggering type:" not in output

    def test_real_type_shown(self):
        output = self._capture_console([_make_result(TriggeringType="MyService")])
        assert "Triggering type: MyService" in output

    def test_per_target_count_in_output(self):
        results = [
            _make_result(ConsumerProjectName="App.Web"),
            _make_result(ConsumerProjectName="App.Api"),
        ]
        output = self._capture_console(results)
        assert "Consumers: 2" in output

    def test_count_is_per_group_not_per_project(self):
        """When a target has multiple triggering types, each group shows its own count."""
        results = [
            _make_result(TriggeringType="ClassA", ConsumerProjectName="App.Web"),
            _make_result(TriggeringType="ClassA", ConsumerProjectName="App.Api"),
            _make_result(TriggeringType="ClassA", ConsumerProjectName="App.Worker"),
            _make_result(TriggeringType="ClassB", ConsumerProjectName="App.Web"),
            _make_result(TriggeringType="ClassB", ConsumerProjectName="App.Api"),
        ]
        output = self._capture_console(results)
        assert "Consumers: 3" in output  # ClassA group
        assert "Consumers: 2" in output  # ClassB group
        assert "Consumers: 5" not in output  # should NOT show total

    def test_header_uses_equals_separator(self):
        output = self._capture_console([_make_result()])
        assert "=" * 60 in output

    def test_empty_results_message(self):
        output = self._capture_console([])
        assert "No consuming relationships found." in output

    def test_graph_metrics_table_columns(self):
        result = _make_result(coupling_score=5.0, fan_in=2, fan_out=3, instability=0.6)
        output = self._capture_console([result], graph_metrics_requested=True)
        assert "Score" in output
        assert "Fan-In" in output
        assert "Fan-Out" in output
        assert "Instab." in output

    def test_instability_two_decimals(self):
        result = _make_result(coupling_score=5.0, fan_in=2, fan_out=3, instability=0.5)
        output = self._capture_console([result], graph_metrics_requested=True)
        assert "0.50" in output
        assert "0.500" not in output

    def test_long_consumer_name(self):
        long_name = "MyCompany.Platform.Services.Authentication.OAuth"
        result = _make_result(ConsumerProjectName=long_name)
        output = self._capture_console([result])
        assert long_name in output

    def test_missing_coupling_score_shows_dash(self):
        result = _make_result(coupling_score=None)
        output = self._capture_console([result], graph_metrics_requested=True)
        assert "\u2014" in output  # em dash

    def test_consumers_sorted_by_coupling_desc(self):
        results = [
            _make_result(
                ConsumerProjectName="Low", coupling_score=1.0, fan_in=0, fan_out=1, instability=0.5
            ),
            _make_result(
                ConsumerProjectName="High",
                coupling_score=10.0,
                fan_in=0,
                fan_out=1,
                instability=0.5,
            ),
        ]
        output = self._capture_console(results, graph_metrics_requested=True)
        high_pos = output.index("High")
        low_pos = output.index("Low")
        assert high_pos < low_pos

    def test_consumers_sorted_alpha_without_metrics(self):
        results = [
            _make_result(ConsumerProjectName="Zebra"),
            _make_result(ConsumerProjectName="Alpha"),
        ]
        output = self._capture_console(results)
        alpha_pos = output.index("Alpha")
        zebra_pos = output.index("Zebra")
        assert alpha_pos < zebra_pos

    def test_scrambled_input_groups_correctly(self):
        """groupby works even when input is not pre-sorted by target/type."""
        results = [
            _make_result(TriggeringType="ClassB", ConsumerProjectName="App.Web"),
            _make_result(TriggeringType="ClassA", ConsumerProjectName="App.Api"),
            _make_result(TriggeringType="ClassB", ConsumerProjectName="App.Api"),
            _make_result(TriggeringType="ClassA", ConsumerProjectName="App.Web"),
            _make_result(TriggeringType="ClassA", ConsumerProjectName="App.Worker"),
        ]
        output = self._capture_console(results)
        assert "Consumers: 3" in output  # ClassA group
        assert "Consumers: 2" in output  # ClassB group


# ── 1d: CSV Cleanup ─────────────────────────────────────────────────


class TestCsvCleanup:
    """Verify CSV formatting fixes."""

    def test_legacy_csv_omits_summaries_column(self, tmp_path):
        buf = tmp_path / "report.csv"
        results = prepare_detailed_results([_make_result()])
        write_csv_report(results, buf)
        text = buf.read_text()
        reader = csv.DictReader(io.StringIO(text))
        assert "ConsumerFileSummaries" not in reader.fieldnames

    def test_legacy_csv_has_8_columns(self, tmp_path):
        buf = tmp_path / "report.csv"
        results = prepare_detailed_results([_make_result()])
        write_csv_report(results, buf)
        text = buf.read_text()
        reader = csv.DictReader(io.StringIO(text))
        assert len(reader.fieldnames) == 8

    def test_legacy_csv_semicolon_solutions(self, tmp_path):
        buf = tmp_path / "report.csv"
        results = prepare_detailed_results([_make_result()])
        write_csv_report(results, buf)
        text = buf.read_text()
        reader = csv.DictReader(io.StringIO(text))
        row = next(reader)
        assert "; " in row["ConsumingSolutions"]
        assert ", " not in row["ConsumingSolutions"]

    def test_impact_csv_semicolons_in_solutions_and_vectors(self, tmp_path):
        buf = tmp_path / "impact.csv"
        report = _make_impact_report(
            solutions=["SolA.sln", "SolB.sln"],
            coupling_vectors=["namespace", "project-ref"],
        )
        write_impact_csv_report(report, buf)
        text = buf.read_text()
        reader = csv.DictReader(io.StringIO(text))
        row = next(reader)
        assert "; " in row["Solutions"]
        assert "; " in row["CouplingVectors"]


# ── Version constant ─────────────────────────────────────────────────


class TestVersionConstant:
    def test_version_importable(self):
        from scatter.__version__ import __version__

        assert isinstance(__version__, str)
        assert __version__[0].isdigit()

    def test_version_reexported_from_package(self):
        import scatter

        assert scatter.__version__ == "2.1.0"


# ── P0 review fix: API key redaction ─────────────────────────────────


class TestMetadataRedaction:
    """Verify _build_metadata does not leak sensitive CLI args."""

    def test_google_api_key_excluded(self):
        from scatter.cli import _build_metadata

        args = argparse.Namespace(
            target_project="x",
            google_api_key="SECRET_KEY_12345",
            verbose=False,
        )
        meta = _build_metadata(args, Path("/repo"), 0.0)
        assert "google_api_key" not in meta["cli_args"]
        assert "SECRET_KEY_12345" not in json.dumps(meta)

    def test_non_sensitive_args_preserved(self):
        from scatter.cli import _build_metadata

        args = argparse.Namespace(
            target_project="Lib.Core",
            google_api_key="SECRET",
            verbose=True,
        )
        meta = _build_metadata(args, Path("/repo"), 0.0)
        assert meta["cli_args"]["target_project"] == "Lib.Core"
        assert meta["cli_args"]["verbose"] is True
