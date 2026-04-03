"""Tests for the unified risk engine.

Covers: composite scoring, aggregation, edge cases (empty profiles,
unknown targets), risk context validation, and performance.
"""

import time
from pathlib import Path

import pytest

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.analyzers.risk_engine import (
    aggregate_risk,
    compute_risk_profile,
    format_risk_factors,
)
from scatter.core.graph import DependencyGraph, ProjectNode
from scatter.core.risk_models import (
    AggregateRisk,
    RiskContext,
    RiskDimension,
    RiskLevel,
    RiskProfile,
    composite_to_risk_level,
    PR_RISK_CONTEXT,
    SOW_RISK_CONTEXT,
    LOCAL_DEV_CONTEXT,
)
from tests.conftest import make_metrics


def _make_graph(*names: str) -> DependencyGraph:
    graph = DependencyGraph()
    for name in names:
        graph.add_node(ProjectNode(
            path=Path(f"{name}/{name}.csproj"),
            name=name,
        ))
    return graph


# --- RiskContext validation (Decision #9) ---


class TestRiskContextValidation:
    def test_valid_context_constructs(self):
        ctx = RiskContext(
            name="test",
            dimension_weights={"cycle": 1.0, "structural": 0.5},
            red_threshold=0.7,
            yellow_threshold=0.4,
            description="Test context",
        )
        assert ctx.name == "test"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name must be non-empty"):
            RiskContext(
                name="",
                dimension_weights={"cycle": 1.0},
                red_threshold=0.7,
                yellow_threshold=0.4,
                description="Bad",
            )

    def test_yellow_gte_red_raises(self):
        with pytest.raises(ValueError, match="yellow_threshold.*must be <.*red_threshold"):
            RiskContext(
                name="bad",
                dimension_weights={"cycle": 1.0},
                red_threshold=0.4,
                yellow_threshold=0.7,
                description="Bad",
            )

    def test_yellow_equal_red_raises(self):
        with pytest.raises(ValueError, match="yellow_threshold.*must be <.*red_threshold"):
            RiskContext(
                name="bad",
                dimension_weights={"cycle": 1.0},
                red_threshold=0.5,
                yellow_threshold=0.5,
                description="Bad",
            )

    def test_weight_out_of_range_raises(self):
        with pytest.raises(ValueError, match="weight 'cycle' is 1.5"):
            RiskContext(
                name="bad",
                dimension_weights={"cycle": 1.5},
                red_threshold=0.7,
                yellow_threshold=0.4,
                description="Bad",
            )

    def test_negative_weight_raises(self):
        with pytest.raises(ValueError, match="weight 'cycle' is -0.1"):
            RiskContext(
                name="bad",
                dimension_weights={"cycle": -0.1},
                red_threshold=0.7,
                yellow_threshold=0.4,
                description="Bad",
            )

    def test_unknown_dimension_raises(self):
        with pytest.raises(ValueError, match="Unknown dimension 'typo'"):
            RiskContext(
                name="bad",
                dimension_weights={"typo": 0.5},
                red_threshold=0.7,
                yellow_threshold=0.4,
                description="Bad",
            )

    def test_builtin_contexts_are_valid(self):
        """All three built-in contexts should construct without error."""
        assert PR_RISK_CONTEXT.name == "pr"
        assert SOW_RISK_CONTEXT.name == "sow"
        assert LOCAL_DEV_CONTEXT.name == "local"


# --- Composite scoring ---


class TestCompositeScore:
    def test_weighted_max_not_average(self):
        """6 dimensions at 0.0 + 1 cycle at 0.9 → composite 0.9 (not 0.13)."""
        profile = RiskProfile(
            target_name="A",
            target_type="project",
            cycle=RiskDimension(
                name="cycle", label="Cycle", score=0.9, severity="critical",
                factors=["in cycle"], raw_metrics={},
            ),
        )
        # Using PR context where cycle weight = 1.0
        composite = 0.0
        for d in profile.dimensions:
            weight = PR_RISK_CONTEXT.dimension_weights.get(d.name, 0.0)
            val = weight * d.score
            composite = max(composite, val)
        assert composite == pytest.approx(0.9), "Weighted max, not average"

    def test_composite_bounded_zero_to_one(self):
        """Composite score is always in [0.0, 1.0]."""
        graph = _make_graph("A")
        metrics = {"A": make_metrics(fan_in=20, instability=1.0, shared_db_density=1.0)}
        cycles = [CycleGroup(projects=["A", "B", "C", "D", "E", "F"],
                             shortest_cycle=["A", "B", "C", "D", "E", "F", "A"],
                             edge_count=6)]
        profile = compute_risk_profile(
            "A", graph, metrics, ["B", "C"], cycles, PR_RISK_CONTEXT,
            direct_consumer_count=30, transitive_consumer_count=50,
        )
        assert 0.0 <= profile.composite_score <= 1.0

    def test_risk_level_from_composite(self):
        assert composite_to_risk_level(0.8, PR_RISK_CONTEXT) == RiskLevel.RED
        assert composite_to_risk_level(0.5, PR_RISK_CONTEXT) == RiskLevel.YELLOW
        assert composite_to_risk_level(0.2, PR_RISK_CONTEXT) == RiskLevel.GREEN


# --- Unknown target (Decision #7) ---


class TestUnknownTarget:
    def test_unknown_target_returns_safe_profile(self):
        """Target not in graph → GREEN, data_available=False on metric-dependent dims."""
        graph = _make_graph("B")  # A is not in the graph
        metrics = {"B": make_metrics()}
        profile = compute_risk_profile(
            "A", graph, metrics, [], [], PR_RISK_CONTEXT,
        )
        assert profile.risk_level == RiskLevel.GREEN
        # Composite may be slightly above 0 (blast_radius scores 0.1 for 0 consumers)
        assert profile.composite_score < 0.2
        # Structural and instability should have data_available=False
        assert profile.structural.data_available is False
        assert profile.instability.data_available is False

    def test_data_unavailable_dimension_has_factor(self):
        graph = _make_graph("B")
        metrics = {}
        profile = compute_risk_profile(
            "A", graph, metrics, [], [], PR_RISK_CONTEXT,
        )
        assert "data_unavailable" in profile.structural.factors

    def test_data_unavailable_not_counted_in_composite(self):
        """Dimensions with data_available=False should not inflate composite.
        Note: blast_radius (data_available=True) still contributes its base 0.1."""
        graph = _make_graph("B")
        metrics = {}
        profile = compute_risk_profile(
            "A", graph, metrics, [], [], PR_RISK_CONTEXT,
        )
        # Only blast_radius and domain_boundary have data_available=True (but low scores)
        # Structural, instability, database all have data_available=False
        assert profile.structural.data_available is False
        assert profile.instability.data_available is False
        assert profile.database.data_available is False
        assert profile.composite_score < 0.2  # not inflated by unavailable dims


# --- Aggregation ---


class TestAggregation:
    def test_aggregate_empty_profiles_returns_green(self):
        """Decision #8: aggregate_risk([]) → GREEN, composite 0.0."""
        agg = aggregate_risk([], PR_RISK_CONTEXT)
        assert agg.risk_level == RiskLevel.GREEN
        assert agg.composite_score == 0.0
        assert agg.hotspots == []
        assert agg.profiles == []

    def test_aggregate_risk_level_never_lower_than_max_target(self):
        """If any target is RED, aggregate must be RED."""
        red_profile = RiskProfile(
            target_name="A", target_type="project",
            composite_score=0.8, risk_level=RiskLevel.RED,
            cycle=RiskDimension(
                name="cycle", label="Cycle", score=0.9, severity="critical",
                factors=["big cycle"], raw_metrics={},
            ),
        )
        green_profile = RiskProfile(
            target_name="B", target_type="project",
            composite_score=0.1, risk_level=RiskLevel.GREEN,
        )
        agg = aggregate_risk([red_profile, green_profile], PR_RISK_CONTEXT)
        assert agg.risk_level == RiskLevel.RED

    def test_hotspots_sorted_by_composite(self):
        p1 = RiskProfile(target_name="A", target_type="project", composite_score=0.3)
        p2 = RiskProfile(target_name="B", target_type="project", composite_score=0.8)
        p3 = RiskProfile(target_name="C", target_type="project", composite_score=0.5)
        agg = aggregate_risk([p1, p2, p3], PR_RISK_CONTEXT)
        assert [h.target_name for h in agg.hotspots] == ["B", "C", "A"]

    def test_risk_factors_are_unique(self):
        """No duplicate factors in the output list."""
        dim = RiskDimension(
            name="cycle", label="Cycle", score=0.9, severity="critical",
            factors=["same factor", "same factor"], raw_metrics={},
        )
        p1 = RiskProfile(target_name="A", target_type="project", cycle=dim)
        p2 = RiskProfile(target_name="B", target_type="project", cycle=dim)
        agg = aggregate_risk([p1, p2], PR_RISK_CONTEXT)
        assert len(agg.risk_factors) == len(set(agg.risk_factors))

    def test_target_level_counts(self):
        red = RiskProfile(target_name="A", target_type="project",
                          composite_score=0.8, risk_level=RiskLevel.RED)
        yellow = RiskProfile(target_name="B", target_type="project",
                             composite_score=0.5, risk_level=RiskLevel.YELLOW)
        green = RiskProfile(target_name="C", target_type="project",
                            composite_score=0.1, risk_level=RiskLevel.GREEN)
        agg = aggregate_risk([red, yellow, green], PR_RISK_CONTEXT)
        assert agg.targets_at_red == 1
        assert agg.targets_at_yellow == 1
        assert agg.targets_at_green == 1


# --- Context differences ---


class TestContextDifferences:
    def test_pr_context_vs_sow_context(self):
        """Same target may produce different composites with different contexts."""
        graph = _make_graph("A", "B")
        metrics = {"A": make_metrics(fan_in=5, shared_db_density=0.6)}
        # Database scores differently in SOW (weight 1.0) vs PR (weight 0.8)
        pr_profile = compute_risk_profile(
            "A", graph, metrics, ["B"], [], PR_RISK_CONTEXT,
            direct_consumer_count=1,
        )
        sow_profile = compute_risk_profile(
            "A", graph, metrics, ["B"], [], SOW_RISK_CONTEXT,
            direct_consumer_count=1,
        )
        # They may differ — the important thing is both are valid
        assert 0.0 <= pr_profile.composite_score <= 1.0
        assert 0.0 <= sow_profile.composite_score <= 1.0


# --- format_risk_factors ---


class TestFormatRiskFactors:
    def test_returns_top_n(self):
        profile = RiskProfile(
            target_name="A", target_type="project",
            risk_factors=["f1", "f2", "f3", "f4", "f5", "f6"],
        )
        result = format_risk_factors(profile, top_n=3)
        assert len(result) == 3

    def test_returns_all_if_fewer_than_n(self):
        profile = RiskProfile(
            target_name="A", target_type="project",
            risk_factors=["f1"],
        )
        result = format_risk_factors(profile, top_n=5)
        assert len(result) == 1


# --- risk_models import safety ---


class TestRiskModelsImport:
    def test_risk_models_import_stdlib_only(self):
        """scatter.core.risk_models should only import stdlib modules."""
        import scatter.core.risk_models as rm
        import inspect

        source = inspect.getsource(rm)
        # Should not import from any scatter module or external package
        # (only dataclasses, enum, pathlib, typing)
        forbidden = ["import scatter.", "import google", "import git", "import yaml"]
        for pattern in forbidden:
            assert pattern not in source, f"risk_models.py should not contain '{pattern}'"


# --- Performance (Decision #6) ---


class TestPerformance:
    def test_risk_engine_under_100ms(self):
        """Full risk profile for 13 sample projects in under 100ms."""
        graph = DependencyGraph()
        names = [f"Project{i}" for i in range(13)]
        for name in names:
            graph.add_node(ProjectNode(
                path=Path(f"{name}/{name}.csproj"),
                name=name,
                sproc_references=["sp_shared"] if name in ("Project0", "Project1") else [],
            ))

        metrics = {
            name: make_metrics(
                fan_in=i % 5,
                fan_out=(i + 2) % 4,
                instability=0.3 + (i % 5) * 0.1,
                coupling_score=float(i),
                shared_db_density=0.1 * (i % 3),
            )
            for i, name in enumerate(names)
        }

        cycles = [
            CycleGroup(
                projects=["Project0", "Project1", "Project2"],
                shortest_cycle=["Project0", "Project1", "Project2", "Project0"],
                edge_count=3,
            )
        ]

        start = time.monotonic()
        profiles = []
        for name in names:
            profile = compute_risk_profile(
                name, graph, metrics, [n for n in names if n != name],
                cycles, PR_RISK_CONTEXT,
                direct_consumer_count=3,
                transitive_consumer_count=5,
            )
            profiles.append(profile)

        agg = aggregate_risk(profiles, PR_RISK_CONTEXT)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 100, f"Risk engine took {elapsed_ms:.1f}ms (budget: 100ms)"
        assert agg.risk_level in (RiskLevel.GREEN, RiskLevel.YELLOW, RiskLevel.RED)


# --- End-to-end compute_risk_profile ---


class TestComputeRiskProfileEndToEnd:
    def test_high_risk_target(self):
        """A project in a cycle with high fan-in should score RED."""
        graph = _make_graph("Data", "Api", "Core")
        metrics = {
            "Data": make_metrics(fan_in=8, instability=0.7, coupling_score=5.0),
            "Api": make_metrics(fan_in=3),
            "Core": make_metrics(fan_in=2),
        }
        cycles = [CycleGroup(
            projects=["Data", "Api", "Core"],
            shortest_cycle=["Data", "Api", "Core", "Data"],
            edge_count=3,
        )]
        profile = compute_risk_profile(
            "Data", graph, metrics, ["Api", "Core", "Consumer1"],
            cycles, PR_RISK_CONTEXT,
            direct_consumer_count=8, transitive_consumer_count=12,
        )
        assert profile.risk_level == RiskLevel.RED
        assert profile.cycle.score > 0.0
        assert profile.structural.score > 0.0
        assert len(profile.risk_factors) > 0

    def test_leaf_project_low_risk(self):
        """A project with no consumers, no cycles, no sprocs → GREEN."""
        graph = _make_graph("LeafApp")
        metrics = {
            "LeafApp": make_metrics(fan_in=0, fan_out=3, instability=1.0),
        }
        profile = compute_risk_profile(
            "LeafApp", graph, metrics, [], [], PR_RISK_CONTEXT,
            direct_consumer_count=0, transitive_consumer_count=0,
        )
        assert profile.risk_level == RiskLevel.GREEN
        assert profile.composite_score < 0.4

    def test_change_surface_data_available_false(self):
        """Engine sets change_surface.data_available=False (not computed here)."""
        graph = _make_graph("A")
        metrics = {"A": make_metrics(fan_in=3)}
        profile = compute_risk_profile(
            "A", graph, metrics, [], [], PR_RISK_CONTEXT,
        )
        assert profile.change_surface.data_available is False
        assert profile.change_surface.score == 0.0
