"""Tests for AI report summary — build_summary_stats and generate_report_summary."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.ai.tasks.report_summary import build_summary_stats, generate_report_summary
from scatter.core.models import ConsumerResult, FilterPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    target="TargetA",
    consumer="ConsumerX",
    coupling=None,
    fan_in=None,
    fan_out=None,
    instability=None,
    in_cycle=False,
    solutions=None,
    pipeline=None,
    triggering_type="N/A (Project Reference)",
):
    return ConsumerResult(
        target_project_name=target,
        target_project_path=f"{target}/{target}.csproj",
        triggering_type=triggering_type,
        consumer_project_name=consumer,
        consumer_project_path=f"{consumer}/{consumer}.csproj",
        consuming_solutions=solutions or [],
        pipeline_name=pipeline,
        coupling_score=coupling,
        fan_in=fan_in,
        fan_out=fan_out,
        instability=instability,
        in_cycle=in_cycle,
    )


def _enriched_results():
    """18 consumers mimicking a real monolith result set."""
    return [
        _make_result(
            consumer="WebApp.Admin",
            coupling=6670.9,
            fan_in=4,
            fan_out=181,
            instability=0.978,
            solutions=["Main.sln"],
        ),
        _make_result(
            consumer="WebApp.Participant",
            coupling=4653.6,
            fan_in=2,
            fan_out=119,
            instability=0.983,
            solutions=["Main.sln"],
        ),
        _make_result(
            consumer="Card.Business.Ev1",
            coupling=1127.6,
            fan_in=35,
            fan_out=39,
            instability=0.527,
            solutions=["Core.sln"],
        ),
        _make_result(
            consumer="Card.Business.Tsys",
            coupling=285.7,
            fan_in=9,
            fan_out=18,
            instability=0.667,
            solutions=["Core.sln"],
        ),
        _make_result(
            consumer="ForcePostLib",
            coupling=279.2,
            fan_in=18,
            fan_out=28,
            instability=0.609,
            solutions=["Batch.sln"],
        ),
        _make_result(
            consumer="Demographic.Service",
            coupling=244.1,
            fan_in=18,
            fan_out=20,
            instability=0.526,
            solutions=["Core.sln"],
        ),
        _make_result(
            consumer="Card.Service.Core",
            coupling=223.1,
            fan_in=8,
            fan_out=26,
            instability=0.765,
            solutions=["Core.sln"],
        ),
        _make_result(
            consumer="Card.Business.FirstData",
            coupling=183.3,
            fan_in=9,
            fan_out=13,
            instability=0.591,
        ),
        _make_result(
            consumer="Card.Business.HsaBank",
            coupling=174.2,
            fan_in=4,
            fan_out=25,
            instability=0.862,
        ),
        _make_result(
            consumer="Card.Business.FifthThird",
            coupling=151.7,
            fan_in=10,
            fan_out=21,
            instability=0.677,
        ),
        _make_result(
            consumer="Card.Service", coupling=123.8, fan_in=6, fan_out=11, instability=0.647
        ),
        _make_result(
            consumer="DebitCard.Services", coupling=95.9, fan_in=5, fan_out=20, instability=0.800
        ),
        _make_result(
            consumer="DebitCardService.Test.Library",
            coupling=73.7,
            fan_in=7,
            fan_out=16,
            instability=0.696,
        ),
        _make_result(
            consumer="TokenRemapping.GUI", coupling=20.4, fan_in=0, fan_out=5, instability=1.0
        ),
        _make_result(consumer="Domain.Test", coupling=17.4, fan_in=0, fan_out=6, instability=1.0),
        _make_result(
            consumer="Card.Business.Mbi", coupling=14.9, fan_in=1, fan_out=9, instability=0.9
        ),
        _make_result(
            consumer="Eventing.TestLibrary", coupling=11.9, fan_in=0, fan_out=7, instability=1.0
        ),
        _make_result(
            consumer="Presenters.Web.Participant",
            coupling=6152.9,
            fan_in=8,
            fan_out=122,
            instability=0.938,
            solutions=["Main.sln"],
        ),
    ]


def _pipeline():
    return FilterPipeline(
        search_scope="/workspace",
        total_projects_scanned=1591,
        total_files_scanned=7895,
        stages=[],
    )


# ---------------------------------------------------------------------------
# build_summary_stats tests (pure, no AI)
# ---------------------------------------------------------------------------


class TestBuildSummaryStats:
    def test_basic_stats_with_metrics(self):
        results = _enriched_results()
        stats = build_summary_stats(results, _pipeline())

        assert stats["consumer_count"] == 18
        assert stats["has_graph_metrics"] is True
        assert stats["projects_scanned"] == 1591
        assert "coupling" in stats
        assert stats["coupling"]["min"] == 11.9
        assert stats["coupling"]["max"] == 6670.9

    def test_identifies_outliers(self):
        results = _enriched_results()
        stats = build_summary_stats(results)

        # Median coupling is around 170-ish, so >2x median catches the big ones
        assert "WebApp.Admin" in stats["outliers"]
        assert "WebApp.Participant" in stats["outliers"]
        assert "Presenters.Web.Participant" in stats["outliers"]

    def test_identifies_stable_core(self):
        results = [
            _make_result(
                consumer="StableLib", coupling=100, fan_in=10, fan_out=2, instability=0.17
            ),
            _make_result(consumer="LeafApp", coupling=50, fan_in=0, fan_out=5, instability=1.0),
        ]
        stats = build_summary_stats(results)

        assert "StableLib" in stats["stable_core"]
        assert "LeafApp" not in stats["stable_core"]

    def test_identifies_leaf_nodes(self):
        results = [
            _make_result(
                consumer="StableLib", coupling=100, fan_in=10, fan_out=2, instability=0.17
            ),
            _make_result(consumer="LeafApp", coupling=50, fan_in=0, fan_out=5, instability=1.0),
            _make_result(
                consumer="CycleApp",
                coupling=50,
                fan_in=1,
                fan_out=3,
                instability=0.75,
                in_cycle=True,
            ),
        ]
        stats = build_summary_stats(results)

        assert "LeafApp" in stats["leaf_nodes"]
        assert "CycleApp" not in stats["leaf_nodes"]  # in cycle, excluded
        assert "StableLib" not in stats["leaf_nodes"]

    def test_no_graph_metrics(self):
        results = [
            _make_result(consumer="A", solutions=["X.sln"]),
            _make_result(consumer="B", solutions=["Y.sln"], pipeline="pipeline-1"),
        ]
        stats = build_summary_stats(results)

        assert stats["has_graph_metrics"] is False
        assert "coupling" not in stats
        assert "outliers" not in stats
        assert stats["consumer_names"] == ["A", "B"]
        assert "X.sln" in stats["solutions"]
        assert "pipeline-1" in stats["pipelines"]

    def test_top_consumers_capped_at_5(self):
        results = _enriched_results()
        stats = build_summary_stats(results)

        assert len(stats["top_consumers"]) == 5
        # Should be sorted descending by coupling
        scores = [t["coupling"] for t in stats["top_consumers"]]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# generate_report_summary tests (AI mocked)
# ---------------------------------------------------------------------------


class TestGenerateReportSummary:
    def test_returns_none_when_no_provider(self):
        result = generate_report_summary([_make_result()], None, None, ai_provider=None)
        assert result is None

    def test_returns_none_when_empty_results(self):
        provider = MagicMock()
        result = generate_report_summary([], None, None, ai_provider=provider)
        assert result is None

    def test_returns_summary_on_success(self):
        provider = MagicMock()
        provider.analyze.return_value = MagicMock(
            response=json.dumps({"report": "## Executive Summary\n\nThis is a test report."})
        )

        result = generate_report_summary(
            _enriched_results(), _pipeline(), None, ai_provider=provider
        )
        assert result == "## Executive Summary\n\nThis is a test report."
        provider.analyze.assert_called_once()

    def test_handles_json_decode_error(self):
        provider = MagicMock()
        provider.analyze.return_value = MagicMock(response="not json at all")

        result = generate_report_summary(
            [_make_result(coupling=10, fan_in=1, instability=0.5)],
            None,
            None,
            ai_provider=provider,
        )
        assert result is None

    def test_handles_model_exception(self):
        provider = MagicMock()
        provider.analyze.side_effect = RuntimeError("API down")

        result = generate_report_summary(
            [_make_result(coupling=10, fan_in=1, instability=0.5)],
            None,
            None,
            ai_provider=provider,
        )
        assert result is None

    def test_strips_markdown_fences(self):
        provider = MagicMock()
        provider.analyze.return_value = MagicMock(
            response='```json\n{"report": "Fenced report."}\n```'
        )

        result = generate_report_summary(
            [_make_result(coupling=10, fan_in=1, instability=0.5)],
            None,
            None,
            ai_provider=provider,
        )
        assert result == "Fenced report."


# ---------------------------------------------------------------------------
# Reporter integration tests
# ---------------------------------------------------------------------------


class TestReporterIntegration:
    def test_console_renders_ai_report(self, capsys):
        from scatter.reports.console_reporter import print_console_report

        results = [_make_result(coupling=10, fan_in=1, instability=0.5)]
        print_console_report(results, ai_summary="## Executive Summary\n\nTest report content.")

        captured = capsys.readouterr()
        assert "AI Analysis" in captured.out
        assert "Executive Summary" in captured.out
        assert "Test report content." in captured.out

    def test_console_omits_when_none(self, capsys):
        from scatter.reports.console_reporter import print_console_report

        results = [_make_result(coupling=10, fan_in=1, instability=0.5)]
        print_console_report(results, ai_summary=None)

        captured = capsys.readouterr()
        assert "AI Analysis" not in captured.out

    def test_markdown_includes_ai_report(self):
        from scatter.reports.json_reporter import prepare_detailed_results
        from scatter.reports.markdown_reporter import build_markdown

        results = [_make_result(coupling=10, fan_in=1, instability=0.5)]
        detailed = prepare_detailed_results(results, graph_metrics_requested=True)
        md = build_markdown(
            detailed,
            graph_metrics_requested=True,
            ai_summary="## Executive Summary\n\nNarrative here.",
        )

        assert "## Executive Summary" in md
        assert "Narrative here." in md

    def test_markdown_omits_when_none(self):
        from scatter.reports.json_reporter import prepare_detailed_results
        from scatter.reports.markdown_reporter import build_markdown

        results = [_make_result(coupling=10, fan_in=1, instability=0.5)]
        detailed = prepare_detailed_results(results, graph_metrics_requested=True)
        md = build_markdown(detailed, graph_metrics_requested=True, ai_summary=None)

        assert "Executive Summary" not in md
