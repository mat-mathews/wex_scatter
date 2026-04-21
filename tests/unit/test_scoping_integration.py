"""Integration tests for scatter.analyzers.scoping_analyzer — end-to-end scoping."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scatter.analyzers.scoping_analyzer import run_scoping_analysis
from scatter.core.graph import DependencyGraph, ProjectNode
from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    ImpactReport,
    TargetImpact,
)
from scatter.core.risk_models import AggregateRisk, RiskDimension, RiskLevel
from scatter.core.scoping_models import ScopingReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_ctx(*node_names):
    """Build a GraphContext with named nodes."""
    from scatter.analyzers.graph_enrichment import GraphContext
    from tests.conftest import make_metrics

    graph = DependencyGraph()
    metrics = {}
    for name in node_names:
        node = ProjectNode(path=Path(f"/{name}/{name}.csproj"), name=name)
        graph.add_node(node)
        metrics[name] = make_metrics(fan_in=2, fan_out=1)

    return GraphContext(graph=graph, metrics=metrics, cycles=[], cycle_members=set())


def _make_aggregate_risk(composite=0.4, level=RiskLevel.YELLOW) -> AggregateRisk:
    """Build a minimal AggregateRisk."""
    zero = RiskDimension.zero("structural", "Structural")
    return AggregateRisk(
        profiles=[],
        structural=zero,
        instability=zero,
        cycle=zero,
        database=zero,
        blast_radius=zero,
        domain_boundary=zero,
        change_surface=zero,
        composite_score=composite,
        risk_level=level,
        risk_factors=["test factor"],
        targets_at_red=0,
        targets_at_yellow=1,
        targets_at_green=0,
        total_consumers=3,
        total_transitive=2,
        hotspots=[],
    )


def _make_impact_report(
    target_count=1,
    consumers_per_target=2,
    ambiguity="clear",
    with_risk=True,
) -> ImpactReport:
    """Build a minimal ImpactReport with optional risk data."""
    report = ImpactReport(sow_text="Add tenant isolation to PortalDataService")
    report.ambiguity_level = ambiguity
    report.avg_target_confidence = 0.9

    for i in range(target_count):
        consumers = []
        for j in range(consumers_per_target):
            consumers.append(
                EnrichedConsumer(
                    consumer_path=Path(f"/consumer_{i}_{j}"),
                    consumer_name=f"Consumer{i}_{j}",
                    depth=0 if j == 0 else 1,
                )
            )
        ti = TargetImpact(
            target=AnalysisTarget(target_type="project", name=f"Target{i}"),
            consumers=consumers,
            total_direct=1,
            total_transitive=consumers_per_target - 1,
        )
        report.targets.append(ti)

    if with_risk:
        report.aggregate_risk = _make_aggregate_risk()

    return report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScopingAnalysis:
    def test_produces_scoping_report(self):
        """run_scoping_analysis produces a valid ScopingReport."""
        report = _make_impact_report()
        graph_ctx = _make_graph_ctx("Target0", "Consumer0_0", "Consumer0_1")

        result = run_scoping_analysis(report, graph_ctx)

        assert isinstance(result, ScopingReport)
        assert result.impact_report is report
        assert len(result.effort.categories) == 5
        assert result.effort.total_base_days > 0
        assert result.confidence.level is not None
        assert result.duration_ms >= 0

    def test_reads_stored_aggregate_risk(self):
        """Verify aggregate_risk is read from ImpactReport, not recomputed."""
        report = _make_impact_report(with_risk=True)
        agg = report.aggregate_risk

        result = run_scoping_analysis(report, None)

        assert result.aggregate_risk is agg
        assert result.confidence.composite_score == agg.composite_score

    def test_no_graph_produces_warnings(self):
        """Without graph, warnings should be populated."""
        report = _make_impact_report()

        result = run_scoping_analysis(report, None)

        assert any("graph" in w.lower() for w in result.warnings)
        assert result.effort.total_base_days > 0  # still computes

    def test_no_risk_data(self):
        """Without risk data, composite_score defaults to 0."""
        report = _make_impact_report(with_risk=False)

        result = run_scoping_analysis(report, None)

        assert result.confidence.composite_score == 0.0

    def test_scoping_completes_under_1s(self):
        """Scoping pipeline (excluding impact analysis + AI) completes in <1s."""
        # Build a moderately-sized report: 5 targets, 10 consumers each
        report = _make_impact_report(target_count=5, consumers_per_target=10, with_risk=True)
        # Build graph with all involved nodes
        node_names = []
        for ti in report.targets:
            node_names.append(ti.target.name)
            for c in ti.consumers:
                node_names.append(c.consumer_name)
        graph_ctx = _make_graph_ctx(*node_names)

        result = run_scoping_analysis(report, graph_ctx)

        assert result.duration_ms < 1000, f"Scoping took {result.duration_ms}ms, budget is <1000ms"


class TestScopingFallback:
    def test_scoping_failure_is_catchable(self):
        """Scoping wrapped in try/except — impact report still ships on failure.

        This tests the pattern, not the actual mode handler.
        """
        report = _make_impact_report()

        with patch(
            "scatter.analyzers.scoping_analyzer.assess_database_impact",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                run_scoping_analysis(report, None)

        # The actual fallback is in modes/impact.py which catches this.
        # Here we verify the error propagates so the caller can catch it.


class TestScopingWithAI:
    def test_ai_adjustment_populated(self):
        """When AI provider available, adjustment fields get set."""
        report = _make_impact_report()
        mock_provider = MagicMock()
        mock_model = MagicMock()
        mock_provider.model = mock_model

        mock_response = MagicMock()
        mock_response.text = (
            '{"min_days": 12, "max_days": 22, "adjustment_narrative": "Graph underestimates"}'
        )
        mock_model.generate_content.return_value = mock_response

        result = run_scoping_analysis(report, None, ai_provider=mock_provider)

        assert result.ai_effort_adjustment == "Graph underestimates"
        assert result.ai_effort_min_days == 12
        assert result.ai_effort_max_days == 22

    def test_ai_failure_graceful(self):
        """AI failure doesn't crash scoping."""
        report = _make_impact_report()
        mock_provider = MagicMock()
        mock_provider.model.generate_content.side_effect = RuntimeError("API down")

        result = run_scoping_analysis(report, None, ai_provider=mock_provider)

        assert result.ai_effort_adjustment is None
        assert result.effort.total_base_days > 0  # graph baseline still ships
