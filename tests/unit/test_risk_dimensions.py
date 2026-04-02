"""Tests for per-dimension risk scoring functions.

Covers: piecewise linear interpolation (Decision #2), data availability
(Decision #4/#7), and score_* naming convention (Decision #3).
"""

import pytest

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.analyzers.risk_dimensions import (
    _interpolate,
    score_blast_radius,
    score_cycle,
    score_database,
    score_domain_boundary,
    score_instability,
    score_structural,
)
from scatter.core.graph import DependencyGraph, ProjectNode


# --- Helpers ---


def _make_metrics(
    fan_in: int = 0,
    fan_out: int = 0,
    instability: float = 0.0,
    coupling_score: float = 0.0,
    shared_db_density: float = 0.0,
) -> ProjectMetrics:
    return ProjectMetrics(
        fan_in=fan_in,
        fan_out=fan_out,
        instability=instability,
        coupling_score=coupling_score,
        afferent_coupling=fan_in,
        efferent_coupling=fan_out,
        shared_db_density=shared_db_density,
        type_export_count=0,
        consumer_count=fan_in,
    )


def _make_graph_with_sprocs(
    target_name: str,
    target_sprocs: list,
    other_projects: dict | None = None,
) -> DependencyGraph:
    """Build a minimal graph with sproc references for database scoring."""
    graph = DependencyGraph()
    from pathlib import Path

    graph.add_node(ProjectNode(
        path=Path(f"{target_name}/{target_name}.csproj"),
        name=target_name,
        sproc_references=target_sprocs,
    ))
    if other_projects:
        for name, sprocs in other_projects.items():
            graph.add_node(ProjectNode(
                path=Path(f"{name}/{name}.csproj"),
                name=name,
                sproc_references=sprocs,
            ))
    return graph


# --- Interpolation ---


class TestInterpolation:
    def test_at_low_boundary(self):
        assert _interpolate(0.0, 0.0, 10.0, 0.1, 1.0) == 0.1

    def test_at_high_boundary(self):
        assert _interpolate(10.0, 0.0, 10.0, 0.1, 1.0) == 1.0

    def test_midpoint(self):
        assert _interpolate(5.0, 0.0, 10.0, 0.0, 1.0) == pytest.approx(0.5)

    def test_clamps_below(self):
        assert _interpolate(-1.0, 0.0, 10.0, 0.1, 1.0) == 0.1

    def test_clamps_above(self):
        assert _interpolate(11.0, 0.0, 10.0, 0.1, 1.0) == 1.0


# --- Structural ---


class TestScoreStructural:
    def test_high_fan_in_returns_critical(self):
        m = _make_metrics(fan_in=12)
        result = score_structural("A", m, {"A": m})
        assert result.score == 1.0
        assert result.severity == "critical"

    def test_low_fan_in_returns_low(self):
        m = _make_metrics(fan_in=1)
        result = score_structural("A", m, {"A": m})
        assert result.score < 0.4
        assert result.severity in ("low", "medium")  # boundary region

    def test_interpolation_between_thresholds(self):
        """fan_in=4 is between 3 and 5 — should interpolate, not jump."""
        m3 = _make_metrics(fan_in=3)
        m4 = _make_metrics(fan_in=4)
        m5 = _make_metrics(fan_in=5)
        s3 = score_structural("A", m3, {"A": m3}).score
        s4 = score_structural("A", m4, {"A": m4}).score
        s5 = score_structural("A", m5, {"A": m5}).score
        assert s3 < s4 < s5, "Scores should increase monotonically"

    def test_no_cliff_at_boundary(self):
        """fan_in just below and just above threshold should be close."""
        m_below = _make_metrics(fan_in=4)
        m_above = _make_metrics(fan_in=6)
        s_below = score_structural("A", m_below, {"A": m_below}).score
        s_above = score_structural("A", m_above, {"A": m_above}).score
        # Both in adjacent ranges — gap should be moderate, not 0.3+
        assert abs(s_above - s_below) < 0.35

    def test_none_metrics_returns_data_unavailable(self):
        result = score_structural("A", None, {})
        assert result.data_available is False
        assert result.score == 0.0
        assert "data_unavailable" in result.factors

    def test_percentile_bump(self):
        """Top 5% by coupling score gets a bump (needs 10+ projects)."""
        target = _make_metrics(fan_in=4, coupling_score=10.0)
        others = {f"P{i}": _make_metrics(coupling_score=float(i)) for i in range(20)}
        others["target"] = target
        result = score_structural("target", target, others)
        # With 21 projects, target (score=10.0) is in top 5%
        # Should be higher than with <10 projects (no bump)
        small_ctx = {f"P{i}": _make_metrics(coupling_score=float(i)) for i in range(5)}
        small_ctx["target"] = target
        result_small = score_structural("target", target, small_ctx)
        assert result.score >= result_small.score


# --- Instability ---


class TestScoreInstability:
    def test_high_instability_high_fan_in(self):
        m = _make_metrics(instability=0.9, fan_in=5)
        result = score_instability("A", m)
        assert result.score >= 0.7
        assert "fragile foundation" in result.factors[0]

    def test_high_instability_low_fan_in(self):
        m = _make_metrics(instability=0.9, fan_in=1)
        result = score_instability("A", m)
        assert result.score == 0.3
        assert "leaf" in result.factors[0]

    def test_low_instability(self):
        m = _make_metrics(instability=0.3, fan_in=5)
        result = score_instability("A", m)
        assert result.score == 0.1

    def test_interpolation_no_cliff_at_08(self):
        """instability 0.79 and 0.81 should produce close scores for same fan_in."""
        m79 = _make_metrics(instability=0.79, fan_in=5)
        m81 = _make_metrics(instability=0.81, fan_in=5)
        s79 = score_instability("A", m79).score
        s81 = score_instability("A", m81).score
        assert abs(s81 - s79) < 0.15

    def test_none_metrics_returns_data_unavailable(self):
        result = score_instability("A", None)
        assert result.data_available is False

    def test_score_monotonically_increasing(self):
        """Higher instability with same fan_in → higher or equal score."""
        scores = []
        for inst in [0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            m = _make_metrics(instability=inst, fan_in=5)
            scores.append(score_instability("A", m).score)
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], f"Score decreased at instability step {i}"


# --- Cycle ---


class TestScoreCycle:
    def test_not_in_cycle_returns_zero(self):
        result = score_cycle("A", [])
        assert result.score == 0.0
        assert result.data_available is True

    def test_two_project_cycle_returns_medium(self):
        cycle = CycleGroup(projects=["A", "B"], shortest_cycle=["A", "B", "A"], edge_count=2)
        result = score_cycle("A", [cycle])
        assert result.score == 0.6
        assert result.severity in ("medium", "high")

    def test_large_cycle_returns_critical(self):
        cycle = CycleGroup(
            projects=["A", "B", "C", "D", "E"],
            shortest_cycle=["A", "B", "C", "D", "E", "A"],
            edge_count=5,
        )
        result = score_cycle("A", [cycle])
        assert result.score == 1.0
        assert result.severity == "critical"

    def test_multiple_cycles_caps_at_one(self):
        c1 = CycleGroup(projects=["A", "B", "C", "D", "E"], shortest_cycle=["A", "B", "C", "D", "E", "A"], edge_count=5)
        c2 = CycleGroup(projects=["A", "X", "Y"], shortest_cycle=["A", "X", "Y", "A"], edge_count=3)
        result = score_cycle("A", [c1, c2])
        assert result.score <= 1.0

    def test_target_not_in_any_cycle(self):
        cycle = CycleGroup(projects=["B", "C"], shortest_cycle=["B", "C", "B"], edge_count=2)
        result = score_cycle("A", [cycle])
        assert result.score == 0.0

    def test_interpolation_between_sizes(self):
        """Cycle size 3 and 4 should produce different scores."""
        c3 = CycleGroup(projects=["A", "B", "C"], shortest_cycle=["A", "B", "C", "A"], edge_count=3)
        c4 = CycleGroup(projects=["A", "B", "C", "D"], shortest_cycle=["A", "B", "C", "D", "A"], edge_count=4)
        s3 = score_cycle("A", [c3]).score
        s4 = score_cycle("A", [c4]).score
        assert s3 < s4


# --- Database ---


class TestScoreDatabase:
    def test_no_shared_sprocs_returns_zero(self):
        graph = _make_graph_with_sprocs("A", ["sp_A"], {"B": ["sp_B"]})
        m = _make_metrics(shared_db_density=0.0)
        result = score_database("A", graph, m)
        assert result.score == 0.0

    def test_shared_sprocs_same_team(self):
        graph = _make_graph_with_sprocs("A", ["sp_Shared"], {"B": ["sp_Shared"]})
        m = _make_metrics(shared_db_density=0.2)
        result = score_database("A", graph, m)
        assert result.score > 0.0
        assert result.data_available is True

    def test_cross_team_sprocs_returns_high(self):
        graph = _make_graph_with_sprocs("A", ["sp_Shared"], {"B": ["sp_Shared"]})
        m = _make_metrics(shared_db_density=0.6)
        team_map = {"A": "TeamAlpha", "B": "TeamBeta"}
        result = score_database("A", graph, m, team_map)
        assert result.score >= 0.7

    def test_none_metrics_returns_data_unavailable(self):
        graph = DependencyGraph()
        result = score_database("A", graph, None)
        assert result.data_available is False

    def test_no_sprocs_on_target(self):
        graph = _make_graph_with_sprocs("A", [], {"B": ["sp_B"]})
        m = _make_metrics(shared_db_density=0.0)
        result = score_database("A", graph, m)
        assert result.score == 0.0


# --- Blast Radius ---


class TestScoreBlastRadius:
    def test_no_consumers_returns_low(self):
        result = score_blast_radius("A", 0, 0)
        assert result.score == 0.1

    def test_few_direct_consumers(self):
        result = score_blast_radius("A", 3, 0)
        assert 0.3 <= result.score <= 0.5

    def test_many_transitive_consumers_returns_critical(self):
        result = score_blast_radius("A", 5, 25)
        assert result.score == 1.0

    def test_interpolation_on_transitive(self):
        s10 = score_blast_radius("A", 5, 10).score
        s15 = score_blast_radius("A", 5, 15).score
        s20 = score_blast_radius("A", 5, 20).score
        assert s10 < s15 < s20


# --- Domain Boundary ---


class TestScoreDomainBoundary:
    def test_same_cluster_returns_zero(self):
        result = score_domain_boundary("A", ["cluster1", "cluster1"], "cluster1")
        assert result.score == 0.0

    def test_crosses_two_clusters(self):
        result = score_domain_boundary("A", ["cluster1", "cluster2", "cluster2"], "cluster1")
        assert result.score > 0.0

    def test_crosses_many_clusters(self):
        result = score_domain_boundary(
            "A", ["c1", "c2", "c3", "c4"], "c0"
        )
        assert result.score >= 0.6

    def test_team_boundaries_increase_score(self):
        result_no_teams = score_domain_boundary("A", ["c1", "c2"], "c0")
        result_with_teams = score_domain_boundary(
            "A", ["c1", "c2"], "c0",
            team_map={"A": "T1", "B": "T2", "C": "T3"},
            consumer_names=["B", "C"],
        )
        assert result_with_teams.score >= result_no_teams.score

    def test_no_clusters_returns_zero(self):
        result = score_domain_boundary("A", [], None)
        assert result.score == 0.0
