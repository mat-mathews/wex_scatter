"""Tests for scatter.analyzers.effort_estimator — effort heuristics."""

from pathlib import Path

import pytest

from scatter.analyzers.effort_estimator import (
    compute_confidence_band,
    estimate_effort,
    _compute_investigation,
    _compute_implementation,
    _compute_testing,
    _compute_integration_risk,
    _compute_db_migration,
    _make_category,
)
from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    ImpactReport,
    TargetImpact,
)
from scatter.core.scoping_models import (
    ConfidenceLevel,
    DatabaseImpact,
    SharedSprocGroup,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(
    targets=1,
    direct_per_target=0,
    depth1_per_target=0,
    depth2_per_target=0,
    ambiguity="clear",
) -> ImpactReport:
    """Build a minimal ImpactReport with specified consumer counts."""
    report = ImpactReport(sow_text="test", ambiguity_level=ambiguity)
    for i in range(targets):
        consumers = []
        for d in range(direct_per_target):
            consumers.append(
                EnrichedConsumer(
                    consumer_path=Path(f"/c/d{d}_{i}"),
                    consumer_name=f"Direct{d}_{i}",
                    depth=0,
                )
            )
        for d in range(depth1_per_target):
            consumers.append(
                EnrichedConsumer(
                    consumer_path=Path(f"/c/t1_{d}_{i}"),
                    consumer_name=f"Trans1_{d}_{i}",
                    depth=1,
                )
            )
        for d in range(depth2_per_target):
            consumers.append(
                EnrichedConsumer(
                    consumer_path=Path(f"/c/t2_{d}_{i}"),
                    consumer_name=f"Trans2_{d}_{i}",
                    depth=2,
                )
            )
        ti = TargetImpact(
            target=AnalysisTarget(target_type="project", name=f"Target{i}"),
            consumers=consumers,
            total_direct=direct_per_target,
            total_transitive=depth1_per_target + depth2_per_target,
        )
        report.targets.append(ti)
    return report


def _make_db_impact(sproc_count=0, high_sharing=0) -> DatabaseImpact:
    sprocs = []
    for i in range(sproc_count):
        count = 4 if i < high_sharing else 2
        sprocs.append(
            SharedSprocGroup(sproc_name=f"sp_{i}", projects=["A", "B"], project_count=count)
        )
    return DatabaseImpact(
        shared_sprocs=sprocs,
        total_shared_sprocs=sproc_count,
        migration_complexity="low" if sproc_count else "none",
    )


# ---------------------------------------------------------------------------
# TestInvestigation
# ---------------------------------------------------------------------------


class TestInvestigation:
    def test_1_target_no_cycles_no_clusters(self):
        """1 target, no cycles, no clusters -> 0.5 clamped to 1.0."""
        result = _compute_investigation(target_count=1, extra_clusters=0, has_cycles=False)
        assert result == 1.0  # clamped from 0.5

    def test_3_targets_2_clusters_cycle(self):
        """3 targets, 2 clusters, cycle -> clamped to 3.0."""
        result = _compute_investigation(target_count=3, extra_clusters=2, has_cycles=True)
        # 0.5*3 + 0.5*(2-1) + 1.0 = 1.5 + 0.5 + 1.0 = 3.0
        assert result == 3.0

    def test_many_targets_clamped(self):
        """Many targets should clamp at 3.0."""
        result = _compute_investigation(target_count=10, extra_clusters=5, has_cycles=True)
        assert result == 3.0

    def test_zero_targets_clamped_to_min(self):
        result = _compute_investigation(target_count=0, extra_clusters=0, has_cycles=False)
        assert result == 1.0  # min clamp


# ---------------------------------------------------------------------------
# TestImplementation
# ---------------------------------------------------------------------------


class TestImplementation:
    def test_3_direct_2_depth1_1_depth2(self):
        """3 direct + 2 depth-1 + 1 depth-2 = 3.0 + 1.0 + 0.25 = 4.25."""
        result = _compute_implementation(direct=3, depth1=2, depth2=1)
        assert result == pytest.approx(4.25)

    def test_15_direct_sublinear(self):
        """15 direct: min(15,5)*1.0 + max(0,10)*0.3 = 5.0 + 3.0 = 8.0."""
        result = _compute_implementation(direct=15, depth1=0, depth2=0)
        assert result == pytest.approx(8.0)

    def test_5_direct_exact_threshold(self):
        result = _compute_implementation(direct=5, depth1=0, depth2=0)
        assert result == pytest.approx(5.0)

    def test_zero_consumers(self):
        result = _compute_implementation(direct=0, depth1=0, depth2=0)
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestTesting
# ---------------------------------------------------------------------------


class TestTesting:
    def test_2_direct_1_sproc_cross_domain(self):
        """2 direct, 1 sproc, cross-domain -> 0.5*2 + 1.0 + 0.5 = 2.5."""
        result = _compute_testing(direct=2, shared_sprocs=1, cross_domain=True)
        assert result == pytest.approx(2.5)

    def test_no_consumers(self):
        result = _compute_testing(direct=0, shared_sprocs=0, cross_domain=False)
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestIntegrationRisk
# ---------------------------------------------------------------------------


class TestIntegrationRisk:
    def test_zero_case(self):
        """Nothing applies -> 0.0."""
        result = _compute_integration_risk(
            has_cycles=False, shared_sprocs=0, extra_clusters=0, fan_in_gt5=False
        )
        assert result == pytest.approx(0.0)

    def test_all_factors_active(self):
        """cycle + 2 sprocs + 3 extra clusters + fan-in>5."""
        result = _compute_integration_risk(
            has_cycles=True, shared_sprocs=2, extra_clusters=3, fan_in_gt5=True
        )
        # 1.0 + 0.5*2 + 1.0*(3-1) + 0.5 = 1.0 + 1.0 + 2.0 + 0.5 = 4.5
        assert result == pytest.approx(4.5)


# ---------------------------------------------------------------------------
# TestDatabaseMigration
# ---------------------------------------------------------------------------


class TestDatabaseMigration:
    def test_no_sprocs(self):
        assert _compute_db_migration(shared_sprocs=0, high_sharing_sprocs=0) == 0.0

    def test_2_sprocs_low_sharing(self):
        """2 sprocs, all <= 3 sharing = 2.0."""
        assert _compute_db_migration(shared_sprocs=2, high_sharing_sprocs=0) == pytest.approx(2.0)

    def test_1_sproc_high_sharing(self):
        """1 sproc with >3 sharing = 1.0 + 2.0 = 3.0."""
        assert _compute_db_migration(shared_sprocs=1, high_sharing_sprocs=1) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# TestConfidenceBand
# ---------------------------------------------------------------------------


class TestConfidenceBand:
    def test_high_clear(self):
        band = compute_confidence_band(composite_score=0.1, ambiguity_level="clear")
        assert band.level == ConfidenceLevel.HIGH
        assert band.band_pct == pytest.approx(0.20)
        assert not band.was_widened

    def test_moderate_clear(self):
        band = compute_confidence_band(composite_score=0.5, ambiguity_level="clear")
        assert band.level == ConfidenceLevel.MODERATE
        assert band.band_pct == pytest.approx(0.30)

    def test_low(self):
        band = compute_confidence_band(composite_score=0.8, ambiguity_level="clear")
        assert band.level == ConfidenceLevel.LOW
        assert band.band_pct == pytest.approx(0.50)

    def test_vague_widens_high_to_moderate(self):
        band = compute_confidence_band(composite_score=0.1, ambiguity_level="vague")
        assert band.level == ConfidenceLevel.MODERATE
        assert band.was_widened

    def test_vague_widens_moderate_to_low(self):
        band = compute_confidence_band(composite_score=0.5, ambiguity_level="vague")
        assert band.level == ConfidenceLevel.LOW
        assert band.was_widened

    def test_vague_low_stays_low(self):
        band = compute_confidence_band(composite_score=0.8, ambiguity_level="vague")
        assert band.level == ConfidenceLevel.LOW
        assert not band.was_widened  # already at LOW


# ---------------------------------------------------------------------------
# TestBandApplication
# ---------------------------------------------------------------------------


class TestBandApplication:
    def test_band_math(self):
        """base 10.0 with 20% band -> min 8.0, max 12.0."""
        cat = _make_category("test", 10.0, 1.0, 0.20, ["test"])
        assert cat.min_days == pytest.approx(8.0)
        assert cat.max_days == pytest.approx(12.0)

    def test_totals_sum_correctly(self):
        """Verify total_min == sum(c.min_days) and total_max == sum(c.max_days)."""
        report = _make_report(targets=2, direct_per_target=3, depth1_per_target=1)
        band = compute_confidence_band(0.2, "clear")
        db = _make_db_impact()
        effort = estimate_effort(report, None, db, band)

        assert effort.total_min_days == pytest.approx(sum(c.min_days for c in effort.categories))
        assert effort.total_max_days == pytest.approx(sum(c.max_days for c in effort.categories))
        assert effort.total_base_days == pytest.approx(sum(c.base_days for c in effort.categories))


# ---------------------------------------------------------------------------
# TestMultiplier
# ---------------------------------------------------------------------------


class TestMultiplier:
    def test_multiplier_applied(self):
        """multiplier 1.5 x base 10.0 = 15.0 -> then band applied."""
        cat = _make_category("test", 10.0, 1.5, 0.20, ["test"])
        assert cat.base_days == pytest.approx(15.0)
        assert cat.min_days == pytest.approx(12.0)
        assert cat.max_days == pytest.approx(18.0)


# ---------------------------------------------------------------------------
# TestNoGraph
# ---------------------------------------------------------------------------


class TestNoGraph:
    def test_no_graph_produces_warnings_free_result(self):
        """graph_ctx=None -> all graph-dependent terms = 0, still produces result."""
        report = _make_report(targets=1, direct_per_target=2)
        band = compute_confidence_band(0.0, "clear")
        db = _make_db_impact()

        effort = estimate_effort(
            report=report,
            graph_ctx=None,
            db_impact=db,
            confidence=band,
        )

        # Should still compute — investigation clamped to 1.0, implementation from consumers
        assert effort.total_base_days > 0
        assert len(effort.categories) == 5

    def test_no_graph_no_cycles(self):
        """Without graph, cycle-dependent terms should be 0."""
        report = _make_report(targets=1, direct_per_target=1)
        band = compute_confidence_band(0.0, "clear")
        db = _make_db_impact()

        effort = estimate_effort(report, None, db, band)

        # Integration risk should be 0 (no cycles, no sprocs, no clusters, no fan-in)
        int_risk = next(c for c in effort.categories if c.name == "integration_risk")
        assert int_risk.base_days == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestEstimateEffortIntegration
# ---------------------------------------------------------------------------


class TestEstimateEffortIntegration:
    def test_full_breakdown_has_5_categories(self):
        report = _make_report(targets=1, direct_per_target=3)
        band = compute_confidence_band(0.3, "moderate")
        db = _make_db_impact(sproc_count=1)

        effort = estimate_effort(report, None, db, band)
        names = [c.name for c in effort.categories]
        assert names == [
            "investigation",
            "implementation",
            "testing",
            "integration_risk",
            "database_migration",
        ]

    def test_with_sprocs_adds_db_migration(self):
        report = _make_report(targets=1, direct_per_target=2)
        band = compute_confidence_band(0.2, "clear")
        db = _make_db_impact(sproc_count=2, high_sharing=1)

        effort = estimate_effort(report, None, db, band)
        db_cat = next(c for c in effort.categories if c.name == "database_migration")
        # 1.0*2 + 2.0*1 = 4.0
        assert db_cat.base_days == pytest.approx(4.0)
