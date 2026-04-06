"""Tests for scatter.analyzers.db_impact_analyzer — database impact assessment."""

from pathlib import Path

import pytest

from scatter.analyzers.db_impact_analyzer import (
    assess_database_impact,
    _classify_migration_complexity,
)
from scatter.core.graph import DependencyGraph, ProjectNode
from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    ImpactReport,
    TargetImpact,
)
from scatter.core.scoping_models import SharedSprocGroup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_ctx(*nodes_data):
    """Build a minimal GraphContext with ProjectNodes.

    Each entry: (name, [sproc_refs])
    """
    from scatter.analyzers.graph_enrichment import GraphContext

    graph = DependencyGraph()
    for name, sprocs in nodes_data:
        node = ProjectNode(path=Path(f"/{name}/{name}.csproj"), name=name)
        node.sproc_references = list(sprocs)
        graph.add_node(node)

    return GraphContext(graph=graph, metrics={}, cycles=[], cycle_members=set())


def _make_report(*target_consumer_pairs) -> ImpactReport:
    """Build a report with targets and consumers.

    Each entry: (target_name, [consumer_names])
    """
    report = ImpactReport(sow_text="test")
    for tname, cnames in target_consumer_pairs:
        consumers = [
            EnrichedConsumer(consumer_path=Path(f"/{cn}"), consumer_name=cn) for cn in cnames
        ]
        ti = TargetImpact(
            target=AnalysisTarget(target_type="project", name=tname),
            consumers=consumers,
            total_direct=len(consumers),
        )
        report.targets.append(ti)
    return report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSharedSprocGrouping:
    def test_finds_shared_sprocs(self):
        """Sproc used by 2+ projects where at least one is involved."""
        graph_ctx = _make_graph_ctx(
            ("ProjectA", ["sp_shared", "sp_solo_a"]),
            ("ProjectB", ["sp_shared", "sp_solo_b"]),
            ("ProjectC", ["sp_shared"]),
        )
        report = _make_report(("ProjectA", ["ProjectB"]))

        result = assess_database_impact(report, graph_ctx)

        assert result.total_shared_sprocs == 1
        assert result.shared_sprocs[0].sproc_name == "sp_shared"
        assert result.shared_sprocs[0].project_count == 3

    def test_no_shared_sprocs(self):
        """No sprocs shared across projects."""
        graph_ctx = _make_graph_ctx(
            ("ProjectA", ["sp_a"]),
            ("ProjectB", ["sp_b"]),
        )
        report = _make_report(("ProjectA", ["ProjectB"]))

        result = assess_database_impact(report, graph_ctx)
        assert result.total_shared_sprocs == 0
        assert result.migration_complexity == "none"

    def test_shared_sproc_not_involving_our_projects(self):
        """Shared sprocs that don't involve our analysis targets are excluded."""
        graph_ctx = _make_graph_ctx(
            ("ProjectA", ["sp_only_a"]),
            ("ProjectX", ["sp_xy"]),
            ("ProjectY", ["sp_xy"]),
        )
        report = _make_report(("ProjectA", []))

        result = assess_database_impact(report, graph_ctx)
        assert result.total_shared_sprocs == 0


class TestMigrationComplexity:
    def test_none(self):
        assert _classify_migration_complexity([]) == "none"

    def test_low(self):
        sprocs = [SharedSprocGroup(sproc_name="sp", projects=["A", "B"], project_count=2)]
        assert _classify_migration_complexity(sprocs) == "low"

    def test_moderate(self):
        sprocs = [SharedSprocGroup(sproc_name="sp", projects=["A", "B", "C"], project_count=3)]
        assert _classify_migration_complexity(sprocs) == "moderate"

    def test_high(self):
        sprocs = [SharedSprocGroup(sproc_name="sp", projects=["A", "B", "C", "D"], project_count=4)]
        assert _classify_migration_complexity(sprocs) == "high"


class TestNoGraph:
    def test_no_graph_returns_empty_impact(self):
        report = _make_report(("ProjectA", []))
        result = assess_database_impact(report, None)
        assert result.total_shared_sprocs == 0
        assert result.migration_complexity == "none"
        assert len(result.migration_factors) == 1  # "No graph available" message


class TestMigrationDays:
    def test_migration_days_basic(self):
        """1.0/sproc + 2.0/sproc with >3 consumers."""
        graph_ctx = _make_graph_ctx(
            ("A", ["sp1", "sp2"]),
            ("B", ["sp1", "sp2"]),
            ("C", ["sp1"]),
            ("D", ["sp1"]),
        )
        report = _make_report(("A", ["B"]))
        result = assess_database_impact(report, graph_ctx)

        # sp1: shared by A,B,C,D (4 projects, >3 -> +2.0)
        # sp2: shared by A,B (2 projects, <=3 -> no extra)
        # Total: 2*1.0 + 1*2.0 = 4.0
        assert result.estimated_migration_days == pytest.approx(4.0)
