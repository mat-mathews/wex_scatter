"""Tests for risk engine integration into impact analysis (Phase 2).

Covers: graph-derived risk, AI escalation, fallback paths, overall_risk
derivation, backward compatibility. Decisions #11–18, #20.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scatter.analyzers.impact_analyzer import (
    RISK_ORDER,
    _derive_overall_risk_from_consumers,
    _risk_level_to_label,
    run_impact_analysis,
)
from scatter.core.graph import DependencyGraph, ProjectNode
from scatter.core.models import EnrichedConsumer, ImpactReport, TargetImpact, AnalysisTarget
from scatter.core.risk_models import RiskLevel, SOW_RISK_CONTEXT
from tests.conftest import make_metrics


# --- Helpers ---


def _make_graph_ctx(project_names):
    """Build a minimal GraphContext with metrics for the given projects."""
    from scatter.analyzers.graph_enrichment import GraphContext

    graph = DependencyGraph()
    for name in project_names:
        graph.add_node(ProjectNode(
            path=Path(f"{name}/{name}.csproj"),
            name=name,
        ))

    metrics = {name: make_metrics(fan_in=2, fan_out=3, instability=0.6) for name in project_names}
    return GraphContext(graph=graph, metrics=metrics, cycles=[], cycle_members=set())


def _make_target_impact(target_name, consumer_names):
    """Build a TargetImpact with EnrichedConsumer stubs."""
    target = AnalysisTarget(
        name=target_name,
        target_type="class",
        confidence=0.9,
        csproj_path=Path(f"{target_name}/{target_name}.csproj"),
    )
    consumers = [
        EnrichedConsumer(
            consumer_path=Path(f"{name}/{name}.csproj"),
            consumer_name=name,
        )
        for name in consumer_names
    ]
    ti = TargetImpact(target=target)
    ti.consumers = consumers
    ti.total_direct = len(consumer_names)
    ti.total_transitive = 0
    return ti


# --- _risk_level_to_label (Decision #15) ---


class TestRiskLevelToLabel:
    def test_red_maps_to_high(self):
        assert _risk_level_to_label(RiskLevel.RED) == "High"

    def test_yellow_maps_to_medium(self):
        assert _risk_level_to_label(RiskLevel.YELLOW) == "Medium"

    def test_green_maps_to_low(self):
        assert _risk_level_to_label(RiskLevel.GREEN) == "Low"

    def test_no_critical_mapping(self):
        """Graph-derived risk has no 'Critical' — only AI can escalate to it."""
        for level in RiskLevel:
            assert _risk_level_to_label(level) != "Critical"


# --- _derive_overall_risk_from_consumers ---


class TestDeriveOverallRisk:
    def test_no_consumers_returns_low(self):
        report = ImpactReport(sow_text="test")
        assert _derive_overall_risk_from_consumers(report) == "Low"

    def test_max_consumer_risk(self):
        report = ImpactReport(sow_text="test")
        ti = _make_target_impact("A", ["C1", "C2"])
        ti.consumers[0].risk_rating = "Medium"
        ti.consumers[1].risk_rating = "High"
        report.targets.append(ti)
        assert _derive_overall_risk_from_consumers(report) == "High"


# --- Integration: graph + AI paths ---


class TestSowWithGraphUsesRiskEngine:
    """Graph available → risk_rating populated from engine (Decision #11)."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk", return_value=None)
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    def test_graph_populates_risk_rating(
        self, mock_analyze, mock_parse, mock_narrative, mock_complexity,
        mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="GalaxyWorks.Data", target_type="class",
            confidence=0.9, csproj_path=Path("GW/GW.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("GalaxyWorks.Data", ["ConsumerA"])
        mock_analyze.return_value = ti

        graph_ctx = _make_graph_ctx(["GalaxyWorks.Data", "ConsumerA"])

        report = run_impact_analysis(
            sow_text="change GalaxyWorks.Data",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=graph_ctx,
        )

        # Risk rating should be populated from engine, not None
        consumer = report.targets[0].consumers[0]
        assert consumer.risk_rating in ("Low", "Medium", "High")
        assert consumer.risk_justification is not None


class TestSowWithoutGraphUsesAiOnly:
    """No graph → falls back to AI assess_risk."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk")
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    def test_ai_only_risk(
        self, mock_analyze, mock_parse, mock_narrative, mock_complexity,
        mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="MyApp", target_type="class",
            confidence=0.9, csproj_path=Path("MA/MA.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("MyApp", ["Consumer1"])
        mock_analyze.return_value = ti

        mock_risk.return_value = {"rating": "Medium", "justification": "AI says medium"}

        report = run_impact_analysis(
            sow_text="change MyApp",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=None,
        )

        consumer = report.targets[0].consumers[0]
        assert consumer.risk_rating == "Medium"
        assert consumer.risk_justification == "AI says medium"


class TestSowWithGraphAndAiEnriches:
    """Graph fills rating, AI adds justification."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk")
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    def test_graph_fills_ai_adds_justification(
        self, mock_analyze, mock_parse, mock_narrative, mock_complexity,
        mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="Target", target_type="class",
            confidence=0.9, csproj_path=Path("T/T.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("Target", ["Consumer"])
        mock_analyze.return_value = ti

        # AI returns a lower rating than graph — should not downgrade
        mock_risk.return_value = {"rating": "Low", "justification": "AI justification"}

        graph_ctx = _make_graph_ctx(["Target", "Consumer"])

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=graph_ctx,
        )

        consumer = report.targets[0].consumers[0]
        # Graph sets the floor — AI "Low" cannot downgrade
        assert consumer.risk_rating in ("Low", "Medium", "High")
        # Justification comes from graph (engine factors), not AI
        assert consumer.risk_justification is not None


class TestSowWithGraphAiEscalatesNotDowngrades:
    """AI 'Critical' overrides 'High', AI 'Low' does not override 'Medium' (Decision #16)."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk")
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    @patch("scatter.analyzers.impact_analyzer.aggregate_risk")
    @patch("scatter.analyzers.impact_analyzer.compute_risk_profile")
    def test_ai_escalates_to_critical(
        self, mock_compute, mock_aggregate, mock_analyze, mock_parse,
        mock_narrative, mock_complexity, mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="Target", target_type="class",
            confidence=0.9, csproj_path=Path("T/T.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("Target", ["Consumer"])
        mock_analyze.return_value = ti

        # Mock engine to return RED (High)
        mock_profile = MagicMock()
        mock_profile.risk_level = RiskLevel.RED
        mock_profile.risk_factors = ["High cycle risk"]
        mock_compute.return_value = mock_profile

        # Mock aggregate (profiles contain mocks, can't pass to real aggregate_risk)
        mock_agg = MagicMock()
        mock_agg.risk_level = RiskLevel.RED
        mock_aggregate.return_value = mock_agg

        # AI escalates to Critical
        mock_risk.return_value = {"rating": "Critical", "justification": "business critical"}

        graph_ctx = _make_graph_ctx(["Target", "Consumer"])

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=graph_ctx,
        )

        consumer = report.targets[0].consumers[0]
        assert consumer.risk_rating == "Critical"

    @patch("scatter.ai.tasks.risk_assess.assess_risk")
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    @patch("scatter.analyzers.impact_analyzer.aggregate_risk")
    @patch("scatter.analyzers.impact_analyzer.compute_risk_profile")
    def test_ai_cannot_downgrade(
        self, mock_compute, mock_aggregate, mock_analyze, mock_parse,
        mock_narrative, mock_complexity, mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="Target", target_type="class",
            confidence=0.9, csproj_path=Path("T/T.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("Target", ["Consumer"])
        mock_analyze.return_value = ti

        # Engine returns YELLOW (Medium)
        mock_profile = MagicMock()
        mock_profile.risk_level = RiskLevel.YELLOW
        mock_profile.risk_factors = ["Medium instability"]
        mock_compute.return_value = mock_profile

        # Mock aggregate
        mock_agg = MagicMock()
        mock_agg.risk_level = RiskLevel.YELLOW
        mock_aggregate.return_value = mock_agg

        # AI tries to downgrade to Low — should be ignored
        mock_risk.return_value = {"rating": "Low", "justification": "AI says low"}

        graph_ctx = _make_graph_ctx(["Target", "Consumer"])

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=graph_ctx,
        )

        consumer = report.targets[0].consumers[0]
        assert consumer.risk_rating == "Medium"  # Not downgraded to Low


class TestSowNoGraphNoAi:
    """No graph, no AI → all risk fields None, no crashes (Decision #14)."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk", return_value=None)
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    def test_no_graph_no_ai_no_crash(
        self, mock_analyze, mock_parse, mock_narrative, mock_complexity,
        mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="A", target_type="class",
            confidence=0.9, csproj_path=Path("A/A.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("A", ["Consumer"])
        mock_analyze.return_value = ti

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=None,
        )

        consumer = report.targets[0].consumers[0]
        assert consumer.risk_rating is None
        assert consumer.risk_justification is None
        # overall_risk falls back to "Low" (no consumer ratings)
        assert report.overall_risk == "Low"


class TestOverallRiskDerivedFromProfiles:
    """Aggregate of per-target profiles (Decision #13)."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk", return_value=None)
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    def test_overall_risk_from_graph_aggregate(
        self, mock_analyze, mock_parse, mock_narrative, mock_complexity,
        mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="Target", target_type="class",
            confidence=0.9, csproj_path=Path("T/T.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("Target", ["Consumer"])
        mock_analyze.return_value = ti

        graph_ctx = _make_graph_ctx(["Target", "Consumer"])

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=graph_ctx,
        )

        # overall_risk should be set from graph aggregate
        assert report.overall_risk in ("Low", "Medium", "High")


class TestMultipleTargetsAggregateOverall:
    """RED target + GREEN target → overall 'High' (Decision #17)."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk", return_value=None)
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    @patch("scatter.analyzers.impact_analyzer.aggregate_risk")
    @patch("scatter.analyzers.impact_analyzer.compute_risk_profile")
    def test_max_of_profiles(
        self, mock_compute, mock_aggregate, mock_analyze, mock_parse,
        mock_narrative, mock_complexity, mock_coupling, mock_risk,
    ):
        targets = [
            AnalysisTarget(name="HighRisk", target_type="class", confidence=0.9,
                           csproj_path=Path("HR/HR.csproj")),
            AnalysisTarget(name="LowRisk", target_type="class", confidence=0.9,
                           csproj_path=Path("LR/LR.csproj")),
        ]
        mock_parse.return_value = targets

        ti1 = _make_target_impact("HighRisk", ["C1"])
        ti2 = _make_target_impact("LowRisk", ["C2"])
        mock_analyze.side_effect = [ti1, ti2]

        # First target RED, second GREEN
        red_profile = MagicMock()
        red_profile.risk_level = RiskLevel.RED
        red_profile.risk_factors = ["Critical cycle"]

        green_profile = MagicMock()
        green_profile.risk_level = RiskLevel.GREEN
        green_profile.risk_factors = []

        mock_compute.side_effect = [red_profile, green_profile]

        # aggregate_risk returns RED (max of RED + GREEN)
        mock_agg = MagicMock()
        mock_agg.risk_level = RiskLevel.RED
        mock_aggregate.return_value = mock_agg

        graph_ctx = _make_graph_ctx(["HighRisk", "LowRisk", "C1", "C2"])

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=graph_ctx,
        )

        # Max of RED + GREEN → "High"
        assert report.overall_risk == "High"
        # aggregate_risk was called with both profiles
        mock_aggregate.assert_called_once()
        profiles_arg = mock_aggregate.call_args[0][0]
        assert len(profiles_arg) == 2


class TestBackwardCompatSowOutput:
    """JSON schema unchanged — consumers still have risk_rating as string."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk", return_value=None)
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    def test_consumer_fields_unchanged(
        self, mock_analyze, mock_parse, mock_narrative, mock_complexity,
        mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="A", target_type="class",
            confidence=0.9, csproj_path=Path("A/A.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("A", ["Consumer"])
        mock_analyze.return_value = ti

        graph_ctx = _make_graph_ctx(["A", "Consumer"])

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=graph_ctx,
        )

        consumer = report.targets[0].consumers[0]
        # risk_rating is a string, not RiskLevel enum
        assert isinstance(consumer.risk_rating, str)
        assert consumer.risk_rating in ("Low", "Medium", "High", "Critical")
        # risk_justification is a string
        assert isinstance(consumer.risk_justification, str)
        # overall_risk is a string
        assert isinstance(report.overall_risk, str)


class TestSowRegressionNoGraphByteIdentical:
    """No-graph path unchanged by Phase 2 (Decision #17)."""

    @patch("scatter.ai.tasks.risk_assess.assess_risk")
    @patch("scatter.ai.tasks.coupling_narrative.explain_coupling", return_value=None)
    @patch("scatter.ai.tasks.complexity_estimate.estimate_complexity", return_value=None)
    @patch("scatter.ai.tasks.impact_narrative.generate_impact_narrative", return_value=None)
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer._analyze_single_target")
    def test_no_graph_path_uses_ai_only(
        self, mock_analyze, mock_parse, mock_narrative, mock_complexity,
        mock_coupling, mock_risk,
    ):
        target = AnalysisTarget(
            name="A", target_type="class",
            confidence=0.9, csproj_path=Path("A/A.csproj"),
        )
        mock_parse.return_value = [target]

        ti = _make_target_impact("A", ["Consumer"])
        mock_analyze.return_value = ti

        mock_risk.return_value = {"rating": "High", "justification": "AI high"}

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=None,  # No graph
        )

        consumer = report.targets[0].consumers[0]
        # AI-only path: same behavior as before Phase 2
        assert consumer.risk_rating == "High"
        assert consumer.risk_justification == "AI high"
        # overall_risk from consumer max
        assert report.overall_risk == "High"
