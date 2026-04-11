"""Tests for scatter.analyzers.domain_analyzer — domain boundary detection."""

import pytest
from pathlib import Path
from typing import List

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.analyzers.domain_analyzer import (
    find_clusters,
    _derive_cluster_name,
    _compute_solution_alignment,
    LABEL_PROPAGATION_THRESHOLD,
)
from scatter.analyzers.coupling_analyzer import CycleGroup

REPO_ROOT = Path(__file__).parent.parent.parent


def _make_node(name: str, **kwargs) -> ProjectNode:
    defaults = {
        "path": Path(f"/fake/{name}/{name}.csproj"),
        "name": name,
        "type_declarations": [],
        "sproc_references": [],
    }
    defaults.update(kwargs)
    return ProjectNode(**defaults)


def _make_edge(
    source: str,
    target: str,
    edge_type: str = "project_reference",
    weight: float = 1.0,
    evidence=None,
) -> DependencyEdge:
    return DependencyEdge(
        source=source,
        target=target,
        edge_type=edge_type,
        weight=weight,
        evidence=evidence,
    )


def _galaxy_graph() -> DependencyGraph:
    """Graph mimicking the sample projects structure.

    GalaxyWorks cluster:
      GalaxyWorks.Data (hub)
      MyGalaxyConsumerApp -> GalaxyWorks.Data
      MyGalaxyConsumerApp2 -> GalaxyWorks.Data

    MyDotNetApp cluster:
      MyDotNetApp.Consumer -> MyDotNetApp

    Isolated:
      MyDotNetApp2.Exclude (no edges)
    """
    g = DependencyGraph()
    g.add_node(
        _make_node("GalaxyWorks.Data", type_declarations=["PortalDataService", "DataConfig"])
    )
    g.add_node(_make_node("MyGalaxyConsumerApp"))
    g.add_node(_make_node("MyGalaxyConsumerApp2"))
    g.add_node(_make_node("MyDotNetApp", type_declarations=["AppService"]))
    g.add_node(_make_node("MyDotNetApp.Consumer"))
    g.add_node(_make_node("MyDotNetApp2.Exclude"))

    g.add_edge(_make_edge("MyGalaxyConsumerApp", "GalaxyWorks.Data"))
    g.add_edge(_make_edge("MyGalaxyConsumerApp2", "GalaxyWorks.Data"))
    g.add_edge(_make_edge("MyDotNetApp.Consumer", "MyDotNetApp"))
    return g


def _fully_connected_graph(names: List[str]) -> DependencyGraph:
    """Build fully connected directed graph from names."""
    g = DependencyGraph()
    for n in names:
        g.add_node(_make_node(n))
    for a in names:
        for b in names:
            if a != b:
                g.add_edge(_make_edge(a, b))
    return g


def _two_subgroup_graph(n: int = 25) -> DependencyGraph:
    """Build a graph with two loosely connected dense sub-groups.

    Group A: nodes 0..n//2-1, fully connected among themselves.
    Group B: nodes n//2..n-1, fully connected among themselves.
    One edge from group A to group B (weak bridge).
    """
    g = DependencyGraph()
    names = [f"proj_{i:03d}" for i in range(n)]
    for name in names:
        g.add_node(_make_node(name))

    mid = n // 2
    group_a = names[:mid]
    group_b = names[mid:]

    for a in group_a:
        for b in group_a:
            if a != b:
                g.add_edge(_make_edge(a, b))
    for a in group_b:
        for b in group_b:
            if a != b:
                g.add_edge(_make_edge(a, b))

    # Single bridge edge
    g.add_edge(_make_edge(group_a[0], group_b[0]))
    return g


# ============================================================
# TestFindClusters
# ============================================================


class TestFindClusters:
    def test_two_clusters_in_sample_projects(self):
        """Real-ish graph produces 2 clusters; isolated node excluded."""
        g = _galaxy_graph()
        clusters = find_clusters(g, min_cluster_size=2)

        assert len(clusters) == 2

        # MyDotNetApp cluster gets a common-prefix name
        cluster_names = {c.name for c in clusters}
        assert "MyDotNetApp" in cluster_names

        # All project names across clusters
        all_projects = set()
        for c in clusters:
            all_projects.update(c.projects)

        assert "MyDotNetApp2.Exclude" not in all_projects

    def test_isolated_node_excluded(self):
        """Singleton nodes don't appear in any cluster with min_cluster_size=2."""
        g = _galaxy_graph()
        clusters = find_clusters(g, min_cluster_size=2)

        all_projects = set()
        for c in clusters:
            all_projects.update(c.projects)

        assert "MyDotNetApp2.Exclude" not in all_projects

    def test_fully_connected_cohesion(self):
        """3-node fully connected graph has cohesion 1.0."""
        g = _fully_connected_graph(["A", "B", "C"])
        clusters = find_clusters(g, min_cluster_size=2)

        assert len(clusters) == 1
        c = clusters[0]
        assert c.cohesion == pytest.approx(1.0)
        assert c.internal_edges == 6  # 3 * 2
        assert c.external_edges == 0

    def test_min_cluster_size_filter(self):
        """With min_cluster_size=3, small clusters are excluded."""
        g = _galaxy_graph()
        clusters = find_clusters(g, min_cluster_size=3)

        # Only the GalaxyWorks cluster (3 projects) should survive
        assert len(clusters) == 1
        assert len(clusters[0].projects) >= 3

    def test_single_component_graph(self):
        """4 connected nodes below label prop threshold -> 1 cluster."""
        g = _fully_connected_graph(["W", "X", "Y", "Z"])
        clusters = find_clusters(g, min_cluster_size=2)

        assert len(clusters) == 1
        assert sorted(clusters[0].projects) == ["W", "X", "Y", "Z"]

    def test_empty_graph(self):
        """Empty graph returns empty list."""
        g = DependencyGraph()
        clusters = find_clusters(g)
        assert clusters == []

    def test_deterministic_results(self):
        """5 calls on same graph produce identical results."""
        g = _galaxy_graph()
        results = [find_clusters(g) for _ in range(5)]

        reference = [(c.name, c.projects, c.feasibility_score) for c in results[0]]
        for r in results[1:]:
            current = [(c.name, c.projects, c.feasibility_score) for c in r]
            assert current == reference

    def test_large_component_triggers_label_propagation(self):
        """25-node graph with two sub-groups produces 2 clusters via label prop."""
        g = _two_subgroup_graph(n=LABEL_PROPAGATION_THRESHOLD + 5)
        clusters = find_clusters(g, min_cluster_size=2)

        assert len(clusters) == 2
        sizes = sorted(len(c.projects) for c in clusters)
        # Should roughly split into two groups
        assert sizes[0] >= 2
        assert sizes[1] >= 2
        assert sum(sizes) == LABEL_PROPAGATION_THRESHOLD + 5


# ============================================================
# TestClusterNameDerivation
# ============================================================


class TestClusterNameDerivation:
    def test_common_prefix_name(self):
        """Projects with common prefix get that as cluster name."""
        name = _derive_cluster_name(
            ["GalaxyWorks.Data", "GalaxyWorks.WebPortal", "GalaxyWorks.BatchProcessor"],
            cluster_index=0,
        )
        assert name == "GalaxyWorks"

    def test_no_common_prefix_fallback(self):
        """Projects without common prefix get cluster_N."""
        name = _derive_cluster_name(["Alpha", "Beta", "Gamma"], cluster_index=3)
        assert name == "cluster_3"


# ============================================================
# TestExtractionFeasibility
# ============================================================


class TestExtractionFeasibility:
    def test_easy_extraction(self):
        """Isolated cluster with no external coupling -> easy."""
        g = _fully_connected_graph(["A", "B", "C"])
        clusters = find_clusters(g, min_cluster_size=2)

        assert len(clusters) == 1
        c = clusters[0]
        assert c.extraction_feasibility == "easy"
        assert c.feasibility_score >= 0.75

    def test_hard_extraction(self):
        """Cluster with high external coupling + cross-boundary cycle -> hard."""
        g = DependencyGraph()
        # "Cluster" nodes
        g.add_node(_make_node("X", sproc_references=["sp_Shared1", "sp_Shared2"]))
        g.add_node(_make_node("Y", sproc_references=["sp_Shared1"]))
        g.add_edge(_make_edge("X", "Y"))
        g.add_edge(_make_edge("Y", "X"))

        # External nodes that share sprocs and create heavy coupling
        for i in range(5):
            g.add_node(_make_node(f"Ext_{i}", sproc_references=["sp_Shared1"]))
            g.add_edge(_make_edge(f"Ext_{i}", "X"))
            g.add_edge(_make_edge(f"Ext_{i}", "Y"))

        # Cross-boundary cycle: X -> Ext_0 -> X
        g.add_edge(_make_edge("X", "Ext_0"))

        # Build cluster for just X,Y with a cross-boundary cycle
        cross_cycle = CycleGroup(
            projects=["Ext_0", "X"],
            shortest_cycle=["X", "Ext_0"],
            edge_count=2,
        )
        from scatter.analyzers.domain_analyzer import _build_cluster

        cluster = _build_cluster(["X", "Y"], g, cluster_index=0, cycles=[cross_cycle])

        assert cluster.extraction_feasibility in ("hard", "very_hard")
        assert cluster.feasibility_score < 0.50
        assert len(cluster.shared_db_objects) > 0

    def test_isolated_cluster_is_easy(self):
        """Cluster with zero external edges -> easy."""
        g = DependencyGraph()
        g.add_node(_make_node("P1"))
        g.add_node(_make_node("P2"))
        g.add_edge(_make_edge("P1", "P2"))

        clusters = find_clusters(g, min_cluster_size=2)
        assert len(clusters) == 1
        assert clusters[0].extraction_feasibility == "easy"
        assert clusters[0].coupling_to_outside == 0.0

    def test_api_surface_penalty_with_type_usage(self):
        """type_usage edges with evidence produce non-zero api_surface_penalty."""
        g = DependencyGraph()
        g.add_node(_make_node("Lib", type_declarations=["FooService", "BarHelper"]))
        g.add_node(_make_node("App"))
        # App uses FooService from Lib (crossing boundary)
        g.add_edge(
            _make_edge(
                "App",
                "Lib",
                edge_type="type_usage",
                weight=1.0,
                evidence=["/src/App/Worker.cs:FooService"],
            )
        )

        from scatter.analyzers.domain_analyzer import _build_cluster

        cluster = _build_cluster(["Lib"], g, cluster_index=0)

        # 1 of 2 types externally used -> api_surface_ratio = 0.5
        assert cluster.feasibility_details["api_surface_penalty"] > 0
        assert cluster.feasibility_details["api_surface_penalty"] == pytest.approx(
            0.5 * 0.15  # ratio * weight
        )

    def test_feasibility_details_breakdown(self):
        """All 4 penalty keys present and sum matches 1.0 - score."""
        g = _galaxy_graph()
        clusters = find_clusters(g, min_cluster_size=2)

        for c in clusters:
            assert set(c.feasibility_details.keys()) == {
                "cross_boundary_penalty",
                "shared_db_penalty",
                "cycle_penalty",
                "api_surface_penalty",
            }
            total_penalty = sum(c.feasibility_details.values())
            expected_score = max(0.0, 1.0 - total_penalty)
            assert c.feasibility_score == pytest.approx(expected_score, abs=1e-9)


# === Initiative 9 Phase 4: Solution alignment ===


def _sol_node(name, solutions=None):
    return ProjectNode(
        path=Path(f"/fake/{name}/{name}.csproj"),
        name=name,
        solutions=solutions or [],
    )


class TestSolutionAlignment:
    def test_alignment_all_same_solution(self):
        g = DependencyGraph()
        g.add_node(_sol_node("A", solutions=["X"]))
        g.add_node(_sol_node("B", solutions=["X"]))
        g.add_node(_sol_node("C", solutions=["X"]))

        alignment, dominant = _compute_solution_alignment(["A", "B", "C"], g)
        assert alignment == 1.0
        assert dominant == "X"

    def test_alignment_no_solutions(self):
        g = DependencyGraph()
        g.add_node(_make_node("A"))
        g.add_node(_make_node("B"))

        alignment, dominant = _compute_solution_alignment(["A", "B"], g)
        assert alignment == 0.0
        assert dominant is None

    def test_alignment_mixed(self):
        g = DependencyGraph()
        g.add_node(_sol_node("A", solutions=["X"]))
        g.add_node(_sol_node("B", solutions=["X"]))
        g.add_node(_sol_node("C", solutions=["X"]))
        g.add_node(_sol_node("D", solutions=["Y"]))
        g.add_node(_sol_node("E", solutions=["Y"]))

        alignment, dominant = _compute_solution_alignment(["A", "B", "C", "D", "E"], g)
        assert alignment == pytest.approx(0.6)
        assert dominant == "X"

    def test_dominant_solution_identified(self):
        g = DependencyGraph()
        g.add_node(_sol_node("A", solutions=["Alpha"]))
        g.add_node(_sol_node("B", solutions=["Alpha"]))
        g.add_node(_sol_node("C", solutions=["Beta"]))

        _, dominant = _compute_solution_alignment(["A", "B", "C"], g)
        assert dominant == "Alpha"

    def test_multi_solution_project_counts(self):
        """Project in {X, Y} counts toward dominant X (Fatima)."""
        g = DependencyGraph()
        g.add_node(_sol_node("A", solutions=["X", "Y"]))
        g.add_node(_sol_node("B", solutions=["X"]))
        g.add_node(_sol_node("C", solutions=["Y"]))

        alignment, dominant = _compute_solution_alignment(["A", "B", "C"], g)
        # X: A and B have it → 2 of 3 members → 0.667
        # Y: A and C have it → 2 of 3 members → 0.667
        # Tie-break: max by count then alphabetically → X wins
        assert dominant == "X"
        assert alignment == pytest.approx(2 / 3, abs=0.01)


class TestClusterAlignmentIntegration:
    def test_find_clusters_populates_alignment(self):
        """find_clusters() sets solution_alignment and dominant_solution."""
        g = DependencyGraph()
        g.add_node(_sol_node("A", solutions=["Sol"]))
        g.add_node(_sol_node("B", solutions=["Sol"]))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))

        clusters = find_clusters(g, min_cluster_size=2)
        assert len(clusters) == 1
        assert clusters[0].solution_alignment == 1.0
        assert clusters[0].dominant_solution == "Sol"
