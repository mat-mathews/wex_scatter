"""Tests for Initiative 5 Phase 2: Coupling metrics + cycle detection."""

from pathlib import Path

import pytest

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.analyzers.coupling_analyzer import (
    CycleGroup,
    ProjectMetrics,
    compute_all_metrics,
    compute_solution_metrics,
    detect_cycles,
    rank_by_coupling,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent


def _make_node(name: str, **kwargs) -> ProjectNode:
    defaults = {
        "path": Path(f"/fake/{name}/{name}.csproj"),
        "name": name,
    }
    defaults.update(kwargs)
    return ProjectNode(**defaults)


def _sample_graph() -> DependencyGraph:
    """A -> B -> C, A -> C (namespace_usage)."""
    g = DependencyGraph()
    g.add_node(_make_node("A"))
    g.add_node(_make_node("B"))
    g.add_node(_make_node("C"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="A", target="C", edge_type="namespace_usage"))
    return g


def _cycle_graph_ab() -> DependencyGraph:
    """A -> B -> A (simple cycle)."""
    g = DependencyGraph()
    g.add_node(_make_node("A"))
    g.add_node(_make_node("B"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="A", edge_type="project_reference"))
    return g


def _cycle_graph_abc() -> DependencyGraph:
    """A -> B -> C -> A (triangle cycle)."""
    g = DependencyGraph()
    g.add_node(_make_node("A"))
    g.add_node(_make_node("B"))
    g.add_node(_make_node("C"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="C", target="A", edge_type="project_reference"))
    return g


# ===========================================================================
# TestProjectMetrics
# ===========================================================================
class TestProjectMetrics:
    def test_metrics_construction(self):
        m = ProjectMetrics(
            fan_in=3,
            fan_out=2,
            instability=0.4,
            coupling_score=5.5,
            afferent_coupling=4,
            efferent_coupling=3,
            shared_db_density=0.5,
            type_export_count=10,
            consumer_count=3,
        )
        assert m.fan_in == 3
        assert m.fan_out == 2
        assert m.instability == 0.4
        assert m.coupling_score == 5.5
        assert m.afferent_coupling == 4
        assert m.efferent_coupling == 3
        assert m.shared_db_density == 0.5
        assert m.type_export_count == 10
        assert m.consumer_count == 3

    def test_instability_calculation(self):
        """Verify instability = fan_out / (fan_in + fan_out)."""
        g = _sample_graph()
        metrics = compute_all_metrics(g)

        # C: fan_in=1 (only B->C is project_reference; A->C is namespace_usage),
        # fan_out=0 → instability=0.0
        assert metrics["C"].fan_in == 1
        assert metrics["C"].fan_out == 0
        assert metrics["C"].instability == 0.0
        # But afferent_coupling counts ALL edge types = 2
        assert metrics["C"].afferent_coupling == 2

        # A: fan_in=0, fan_out=1 (project_reference to B) → instability=1.0
        assert metrics["A"].fan_in == 0
        assert metrics["A"].fan_out == 1
        assert metrics["A"].instability == 1.0

    def test_orphan_instability(self):
        """fan_in=0, fan_out=0 → instability=0.0."""
        g = DependencyGraph()
        g.add_node(_make_node("Orphan"))
        metrics = compute_all_metrics(g)
        assert metrics["Orphan"].instability == 0.0
        assert metrics["Orphan"].fan_in == 0
        assert metrics["Orphan"].fan_out == 0


# ===========================================================================
# TestComputeAllMetrics (using sample projects)
# ===========================================================================
class TestComputeAllMetrics:
    @pytest.fixture(scope="class")
    def graph_and_metrics(self):
        from scatter.analyzers.graph_builder import build_dependency_graph

        graph = build_dependency_graph(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )
        metrics = compute_all_metrics(graph)
        return graph, metrics

    def test_galaxyworks_data_metrics(self, graph_and_metrics):
        _, metrics = graph_and_metrics
        m = metrics["GalaxyWorks.Data"]
        # 9 project_reference edges pointing TO Data
        # (WebPortal, BatchProcessor, MyGalaryConsumerApp, MyGalaryConsumerApp2,
        #  GalaxyWorks.Common, GalaxyWorks.Api, GalaxyWorks.Data.Tests,
        #  GalaxyWorks.DevTools, GalaxyWorks.Notifications)
        assert m.fan_in == 9
        assert m.fan_out == 0
        assert m.instability == 0.0

    def test_batch_processor_metrics(self, graph_and_metrics):
        _, metrics = graph_and_metrics
        m = metrics["GalaxyWorks.BatchProcessor"]
        # BatchProcessor references Data + WebPortal
        assert m.fan_out == 2
        # Nobody references BatchProcessor via project_reference
        assert m.fan_in == 0
        assert m.instability == 1.0

    def test_webportal_metrics(self, graph_and_metrics):
        _, metrics = graph_and_metrics
        m = metrics["GalaxyWorks.WebPortal"]
        # WebPortal references Data (fan_out=1)
        assert m.fan_out == 1
        # BatchProcessor references WebPortal (fan_in=1)
        assert m.fan_in == 1
        assert m.instability == 0.5

    def test_exclude_metrics(self, graph_and_metrics):
        _, metrics = graph_and_metrics
        m = metrics["MyDotNetApp2.Exclude"]
        assert m.fan_in == 0
        assert m.fan_out == 0
        assert m.instability == 0.0

    def test_all_projects_have_metrics(self, graph_and_metrics):
        graph, metrics = graph_and_metrics
        assert len(metrics) == graph.node_count
        assert len(metrics) == 13

    def test_coupling_score_ordering(self, graph_and_metrics):
        """GalaxyWorks.Data should have the highest coupling score (most edges)."""
        _, metrics = graph_and_metrics
        ranked = rank_by_coupling(metrics, top_n=3)
        # Data has 4 project_reference incoming + namespace/type edges
        top_name = ranked[0][0]
        assert top_name == "GalaxyWorks.Data"

    def test_rank_by_coupling(self, graph_and_metrics):
        _, metrics = graph_and_metrics
        ranked = rank_by_coupling(metrics, top_n=3)
        assert len(ranked) == 3
        scores = [m.coupling_score for _, m in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_by_coupling_empty(self):
        """rank_by_coupling on empty metrics returns empty list."""
        assert rank_by_coupling({}) == []
        assert rank_by_coupling({}, top_n=5) == []

    def test_shared_db_density(self, graph_and_metrics):
        """GalaxyWorks.Data has sprocs; some are shared with WebPortal/BatchProcessor."""
        graph, metrics = graph_and_metrics
        data_node = graph.get_node("GalaxyWorks.Data")
        if data_node and len(data_node.sproc_references) > 0:
            m = metrics["GalaxyWorks.Data"]
            # At least some sprocs are shared with other projects
            assert m.shared_db_density > 0.0
        else:
            pytest.skip("No sproc references found in GalaxyWorks.Data")

    def test_custom_coupling_weights(self, graph_and_metrics):
        graph, _ = graph_and_metrics
        # All weights zero except namespace_usage at 10x
        custom_weights = {
            "project_reference": 0.0,
            "namespace_usage": 10.0,
            "type_usage": 0.0,
            "sproc_shared": 0.0,
        }
        custom_metrics = compute_all_metrics(graph, coupling_weights=custom_weights)
        default_metrics = compute_all_metrics(graph)

        # GalaxyWorks.Data: has project_reference edges (weighted 1.0 default, 0.0 custom)
        # and namespace_usage edges (weighted 0.5 default, 10.0 custom).
        # The scores must differ.
        data_default = default_metrics["GalaxyWorks.Data"].coupling_score
        data_custom = custom_metrics["GalaxyWorks.Data"].coupling_score
        assert data_default > 0
        assert data_custom > 0
        assert data_default != data_custom


# ===========================================================================
# TestCycleDetection
# ===========================================================================
class TestCycleDetection:
    def test_no_cycles_in_sample_projects(self):
        """The sample projects have no circular dependencies."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        graph = build_dependency_graph(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )
        cycles = detect_cycles(graph)
        assert len(cycles) == 0

    def test_simple_cycle(self):
        """A -> B -> A detected as one CycleGroup."""
        g = _cycle_graph_ab()
        cycles = detect_cycles(g)
        assert len(cycles) == 1
        cg = cycles[0]
        assert cg.size == 2
        assert set(cg.projects) == {"A", "B"}
        assert cg.edge_count == 2
        # Shortest cycle is [A, B] or [B, A]
        assert len(cg.shortest_cycle) == 2
        assert set(cg.shortest_cycle) == {"A", "B"}

    def test_triangle_cycle(self):
        """A -> B -> C -> A detected as CycleGroup with size=3."""
        g = _cycle_graph_abc()
        cycles = detect_cycles(g)
        assert len(cycles) == 1
        cg = cycles[0]
        assert cg.size == 3
        assert set(cg.projects) == {"A", "B", "C"}
        assert cg.edge_count == 3
        assert len(cg.shortest_cycle) == 3

    def test_multiple_independent_sccs(self):
        """Graph with 2 separate SCCs finds both CycleGroups."""
        g = DependencyGraph()
        for name in ["A", "B", "C", "D"]:
            g.add_node(_make_node(name))
        # Cycle 1: A <-> B
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="B", target="A", edge_type="project_reference"))
        # Cycle 2: C <-> D
        g.add_edge(DependencyEdge(source="C", target="D", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="D", target="C", edge_type="project_reference"))

        cycles = detect_cycles(g)
        assert len(cycles) == 2
        all_projects = set()
        for cg in cycles:
            assert cg.size == 2
            all_projects.update(cg.projects)
        assert all_projects == {"A", "B", "C", "D"}

    def test_self_loop(self):
        """A -> A is an SCC of size 1 — NOT reported by detect_cycles (size > 1 filter)."""
        g = DependencyGraph()
        g.add_node(_make_node("A"))
        g.add_edge(DependencyEdge(source="A", target="A", edge_type="project_reference"))
        # Self-loops create an SCC of size 1, which is filtered out
        cycles = detect_cycles(g)
        assert len(cycles) == 0

    def test_large_scc_with_shortest_cycle(self):
        """5-node SCC: A->B->C->D->E->A, plus shortcut A->C."""
        g = DependencyGraph()
        for name in ["A", "B", "C", "D", "E"]:
            g.add_node(_make_node(name))
        # Main cycle: A->B->C->D->E->A
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="C", target="D", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="D", target="E", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="E", target="A", edge_type="project_reference"))
        # Shortcut: A->C (creates shorter cycle A->C->D->E->A = length 4)
        g.add_edge(DependencyEdge(source="A", target="C", edge_type="project_reference"))

        cycles = detect_cycles(g)
        assert len(cycles) == 1
        cg = cycles[0]
        assert cg.size == 5
        # Shortest cycle should be shorter than the full 5-node ring
        # A->C->D->E->A = 4 nodes in path
        assert len(cg.shortest_cycle) <= 4

    def test_scc_sorted_by_size(self):
        """CycleGroups sorted smallest first."""
        g = DependencyGraph()
        for name in ["A", "B", "C", "D", "E"]:
            g.add_node(_make_node(name))
        # Small cycle: A <-> B (size 2)
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="B", target="A", edge_type="project_reference"))
        # Larger cycle: C -> D -> E -> C (size 3)
        g.add_edge(DependencyEdge(source="C", target="D", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="D", target="E", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="E", target="C", edge_type="project_reference"))

        cycles = detect_cycles(g)
        assert len(cycles) == 2
        assert cycles[0].size == 2  # smallest first
        assert cycles[1].size == 3

    def test_no_cycles_in_dag(self):
        """Linear DAG: A -> B -> C -> D has no cycles."""
        g = DependencyGraph()
        for name in ["A", "B", "C", "D"]:
            g.add_node(_make_node(name))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="C", target="D", edge_type="project_reference"))
        cycles = detect_cycles(g)
        assert len(cycles) == 0

    def test_namespace_only_cycle_not_detected_by_default(self):
        """namespace_usage-only cycles are NOT detected by default edge_types filter."""
        g = DependencyGraph()
        g.add_node(_make_node("A"))
        g.add_node(_make_node("B"))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="namespace_usage"))
        g.add_edge(DependencyEdge(source="B", target="A", edge_type="namespace_usage"))

        # Default: only project_reference cycles
        cycles = detect_cycles(g)
        assert len(cycles) == 0

        # Explicit: include namespace_usage
        cycles_all = detect_cycles(g, edge_types={"namespace_usage", "project_reference"})
        assert len(cycles_all) == 1
        assert set(cycles_all[0].projects) == {"A", "B"}

    def test_cycle_size_property(self):
        """CycleGroup.size is a property derived from len(projects)."""
        cg = CycleGroup(
            projects=["A", "B", "C"],
            shortest_cycle=["A", "B", "C"],
            edge_count=3,
        )
        assert cg.size == 3
        assert cg.size == len(cg.projects)


# ===========================================================================
# TestCycleGroup
# ===========================================================================
class TestCycleGroup:
    def test_cycle_group_construction(self):
        cg = CycleGroup(
            projects=["A", "B", "C"],
            shortest_cycle=["A", "B", "C"],
            edge_count=3,
        )
        assert cg.size == 3
        assert cg.projects == ["A", "B", "C"]
        assert cg.shortest_cycle == ["A", "B", "C"]
        assert cg.edge_count == 3

    def test_size_is_property(self):
        """size is always consistent with len(projects)."""
        cg = CycleGroup(projects=["X", "Y"], shortest_cycle=["X", "Y"], edge_count=2)
        assert cg.size == 2
        cg2 = CycleGroup(projects=["A"], shortest_cycle=["A"], edge_count=1)
        assert cg2.size == 1


# === Initiative 9 Phase 3: Solution-level metrics ===


def _make_node(name, solutions=None):
    return ProjectNode(
        path=Path(f"/fake/{name}/{name}.csproj"),
        name=name,
        solutions=solutions or [],
    )


def _sol_graph():
    """Two solutions: X has {A, B}, Y has {C, D}. A→C crosses, A→B is internal."""
    g = DependencyGraph()
    g.add_node(_make_node("A", solutions=["X"]))
    g.add_node(_make_node("B", solutions=["X"]))
    g.add_node(_make_node("C", solutions=["Y"]))
    g.add_node(_make_node("D", solutions=["Y"]))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="A", target="C", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="C", target="D", edge_type="project_reference"))
    return g


class TestSolutionMetrics:
    def test_two_solutions_basic(self):
        g = _sol_graph()
        metrics, bridges = compute_solution_metrics(g)

        assert "X" in metrics
        assert "Y" in metrics

        x = metrics["X"]
        assert x.project_count == 2
        assert x.internal_edges == 1  # A→B
        assert x.external_edges == 1  # A→C
        assert 0.4 < x.cross_solution_ratio < 0.6  # 1/2 = 0.5

        y = metrics["Y"]
        assert y.project_count == 2
        assert y.internal_edges == 1  # C→D
        assert y.external_edges == 1  # A→C (external for Y)

    def test_all_intra_solution(self):
        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["X"]))
        g.add_node(_make_node("B", solutions=["X"]))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))

        metrics, _ = compute_solution_metrics(g)
        assert metrics["X"].cross_solution_ratio == 0.0
        assert metrics["X"].internal_edges == 1
        assert metrics["X"].external_edges == 0

    def test_all_cross_solution(self):
        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["X"]))
        g.add_node(_make_node("B", solutions=["Y"]))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))

        metrics, _ = compute_solution_metrics(g)
        assert metrics["X"].cross_solution_ratio == 1.0
        assert metrics["Y"].cross_solution_ratio == 1.0

    def test_multi_solution_edge_classification(self):
        """Edge A→B where A is in {X,Y} and B is in {X} only.
        Internal to X, external to Y."""
        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["X", "Y"]))
        g.add_node(_make_node("B", solutions=["X"]))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))

        metrics, _ = compute_solution_metrics(g)

        # X: A and B both in X → internal
        assert metrics["X"].internal_edges == 1
        assert metrics["X"].external_edges == 0
        assert metrics["X"].cross_solution_ratio == 0.0

        # Y: A is in Y, B is not → external
        assert metrics["Y"].internal_edges == 0
        assert metrics["Y"].external_edges == 1
        assert metrics["Y"].cross_solution_ratio == 1.0

    def test_unaffiliated_projects_skipped(self):
        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=[]))  # unaffiliated
        g.add_node(_make_node("B", solutions=[]))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))

        metrics, _ = compute_solution_metrics(g)
        assert metrics == {}

    def test_incoming_outgoing_solutions(self):
        g = _sol_graph()  # X={A,B}, Y={C,D}, A→C crosses
        metrics, _ = compute_solution_metrics(g)

        assert "Y" in metrics["X"].outgoing_solutions
        assert "X" in metrics["Y"].incoming_solutions


class TestBridgeProjects:
    def test_bridge_detected(self):
        g = DependencyGraph()
        g.add_node(_make_node("Shared", solutions=["X", "Y", "Z"]))
        g.add_node(_make_node("A", solutions=["X"]))
        g.add_edge(DependencyEdge(source="A", target="Shared", edge_type="project_reference"))

        _, bridges = compute_solution_metrics(g)
        assert "Shared" in bridges

    def test_no_bridge_below_threshold(self):
        g = DependencyGraph()
        g.add_node(_make_node("TwoSols", solutions=["X", "Y"]))
        g.add_node(_make_node("A", solutions=["X"]))
        g.add_edge(DependencyEdge(source="A", target="TwoSols", edge_type="project_reference"))

        _, bridges = compute_solution_metrics(g)
        assert "TwoSols" not in bridges


class TestSolutionHealthObservations:
    def test_high_cross_solution_observation(self):
        from scatter.analyzers.health_analyzer import compute_health_dashboard

        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["X"]))
        g.add_node(_make_node("B", solutions=["Y"]))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))

        proj_metrics = compute_all_metrics(g)
        cycles = detect_cycles(g)
        sol_metrics, bridges = compute_solution_metrics(g)

        dashboard = compute_health_dashboard(
            g,
            proj_metrics,
            cycles,
            solution_metrics=sol_metrics,
            bridge_projects=bridges,
        )

        rules = [o.rule for o in dashboard.observations]
        assert "high_cross_solution_coupling" in rules

    def test_no_observation_below_threshold(self):
        from scatter.analyzers.health_analyzer import compute_health_dashboard

        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["X"]))
        g.add_node(_make_node("B", solutions=["X"]))
        g.add_node(_make_node("C", solutions=["X"]))
        # All internal edges
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))

        proj_metrics = compute_all_metrics(g)
        cycles = detect_cycles(g)
        sol_metrics, bridges = compute_solution_metrics(g)

        dashboard = compute_health_dashboard(
            g,
            proj_metrics,
            cycles,
            solution_metrics=sol_metrics,
            bridge_projects=bridges,
        )

        rules = [o.rule for o in dashboard.observations]
        assert "high_cross_solution_coupling" not in rules

    def test_bridge_project_observation(self):
        from scatter.analyzers.health_analyzer import compute_health_dashboard

        g = DependencyGraph()
        g.add_node(_make_node("Core", solutions=["X", "Y", "Z"]))
        # Add 5 projects depending on Core for fan_in >= 5
        for i in range(5):
            name = f"Consumer{i}"
            g.add_node(_make_node(name, solutions=["X"]))
            g.add_edge(DependencyEdge(source=name, target="Core", edge_type="project_reference"))

        proj_metrics = compute_all_metrics(g)
        cycles = detect_cycles(g)
        sol_metrics, bridges = compute_solution_metrics(g)

        dashboard = compute_health_dashboard(
            g,
            proj_metrics,
            cycles,
            solution_metrics=sol_metrics,
            bridge_projects=bridges,
        )

        rules = [o.rule for o in dashboard.observations]
        assert "solution_bridge_project" in rules
        bridge_obs = [o for o in dashboard.observations if o.rule == "solution_bridge_project"]
        assert bridge_obs[0].project == "Core"

    def test_bridge_no_observation_low_fan_in(self):
        from scatter.analyzers.health_analyzer import compute_health_dashboard

        g = DependencyGraph()
        g.add_node(_make_node("Core", solutions=["X", "Y", "Z"]))
        # Only 2 consumers — fan_in < 5
        for i in range(2):
            name = f"Consumer{i}"
            g.add_node(_make_node(name, solutions=["X"]))
            g.add_edge(DependencyEdge(source=name, target="Core", edge_type="project_reference"))

        proj_metrics = compute_all_metrics(g)
        cycles = detect_cycles(g)
        sol_metrics, bridges = compute_solution_metrics(g)

        dashboard = compute_health_dashboard(
            g,
            proj_metrics,
            cycles,
            solution_metrics=sol_metrics,
            bridge_projects=bridges,
        )

        rules = [o.rule for o in dashboard.observations]
        assert "solution_bridge_project" not in rules
