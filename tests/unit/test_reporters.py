"""Tests for Initiative 5 Phase 6: Graph Reporters + Health Dashboard."""
import csv
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics, SolutionMetrics
from scatter.analyzers.health_analyzer import (
    HealthDashboard,
    Observation,
    compute_health_dashboard,
)
from scatter.analyzers.domain_analyzer import Cluster
from scatter.reports.graph_reporter import (
    build_graph_json,
    generate_mermaid,
    print_graph_report,
    write_graph_csv_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(name: str, **kwargs) -> ProjectNode:
    defaults = {
        "path": Path(f"/fake/{name}/{name}.csproj"),
        "name": name,
    }
    defaults.update(kwargs)
    return ProjectNode(**defaults)


def _sample_graph() -> DependencyGraph:
    """A -> B -> C DAG with mixed edge types."""
    g = DependencyGraph()
    g.add_node(_make_node("A", namespace="A.Core"))
    g.add_node(_make_node("B", namespace="B.Core"))
    g.add_node(_make_node("C", namespace="C.Core"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="A", target="C", edge_type="namespace_usage"))
    return g


def _sample_metrics() -> dict:
    return {
        "A": ProjectMetrics(fan_in=0, fan_out=2, instability=1.0, coupling_score=2.0,
                            afferent_coupling=0, efferent_coupling=2,
                            shared_db_density=0.0, type_export_count=3, consumer_count=0),
        "B": ProjectMetrics(fan_in=1, fan_out=1, instability=0.5, coupling_score=1.5,
                            afferent_coupling=1, efferent_coupling=1,
                            shared_db_density=0.0, type_export_count=2, consumer_count=1),
        "C": ProjectMetrics(fan_in=2, fan_out=0, instability=0.0, coupling_score=1.0,
                            afferent_coupling=2, efferent_coupling=0,
                            shared_db_density=0.0, type_export_count=1, consumer_count=2),
    }


def _cycle_graph() -> DependencyGraph:
    """A -> B -> A cycle."""
    g = DependencyGraph()
    g.add_node(_make_node("A"))
    g.add_node(_make_node("B"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="A", edge_type="project_reference"))
    return g


def _cycle_metrics() -> dict:
    return {
        "A": ProjectMetrics(fan_in=1, fan_out=1, instability=0.5, coupling_score=2.0,
                            afferent_coupling=1, efferent_coupling=1,
                            shared_db_density=0.0, type_export_count=1, consumer_count=1),
        "B": ProjectMetrics(fan_in=1, fan_out=1, instability=0.5, coupling_score=2.0,
                            afferent_coupling=1, efferent_coupling=1,
                            shared_db_density=0.0, type_export_count=1, consumer_count=1),
    }


def _make_cluster(name, projects, **kwargs):
    defaults = dict(
        internal_edges=1,
        external_edges=0,
        cohesion=0.8,
        coupling_to_outside=0.2,
        cross_boundary_dependencies=[],
        shared_db_objects=[],
        extraction_feasibility="moderate",
        feasibility_score=0.65,
        feasibility_details={},
    )
    defaults.update(kwargs)
    return Cluster(name=name, projects=projects, **defaults)


# ===========================================================================
# TestMermaidOutput
# ===========================================================================


class TestMermaidOutput:
    def test_mermaid_basic(self):
        g = _sample_graph()
        result = generate_mermaid(g)
        assert result.startswith("graph TD")
        # project_reference edges present
        assert "A --> B" in result
        assert "B --> C" in result
        # namespace_usage edge should NOT appear (only project_reference)
        lines = result.strip().split("\n")
        arrow_lines = [l for l in lines if "-->" in l]
        assert len(arrow_lines) == 2

    def test_mermaid_dotted_names(self):
        """Dotted project names are sanitized to valid Mermaid IDs."""
        g = DependencyGraph()
        g.add_node(_make_node("GalaxyWorks.Data"))
        g.add_node(_make_node("GalaxyWorks.Web"))
        g.add_edge(DependencyEdge(source="GalaxyWorks.Data", target="GalaxyWorks.Web",
                                  edge_type="project_reference"))
        result = generate_mermaid(g)
        assert "GalaxyWorks_Data" in result
        assert "GalaxyWorks_Web" in result
        # Original names preserved in labels
        assert '["GalaxyWorks.Data"]' in result
        assert "GalaxyWorks_Data --> GalaxyWorks_Web" in result

    def test_mermaid_with_clusters(self):
        g = _sample_graph()
        clusters = [_make_cluster("MyCluster", ["A", "B"])]
        result = generate_mermaid(g, clusters=clusters)
        assert "subgraph" in result

    def test_mermaid_top_n(self):
        g = _sample_graph()
        result = generate_mermaid(g, top_n=2)
        # With top_n=2, at most 2 node IDs should appear as declarations
        lines = result.strip().split("\n")
        # Count node declaration lines (contain ["..."])
        node_lines = [l for l in lines if '["' in l and "-->" not in l]
        assert len(node_lines) <= 2

    def test_mermaid_empty_graph(self):
        g = DependencyGraph()
        result = generate_mermaid(g)
        assert result == "graph TD\n"


# ===========================================================================
# TestHealthDashboard
# ===========================================================================


class TestHealthDashboard:
    def test_computes_averages(self):
        g = _sample_graph()
        metrics = _sample_metrics()
        dashboard = compute_health_dashboard(g, metrics, [])
        assert isinstance(dashboard.avg_fan_in, float)
        assert isinstance(dashboard.avg_fan_out, float)
        assert dashboard.avg_fan_in == pytest.approx(1.0, abs=0.01)
        assert dashboard.avg_fan_out == pytest.approx(1.0, abs=0.01)

    def test_stable_core_observation(self):
        """High fan_in + low instability triggers stable_core."""
        g = DependencyGraph()
        g.add_node(_make_node("Core"))
        metrics = {
            "Core": ProjectMetrics(
                fan_in=7, fan_out=0, instability=0.0, coupling_score=5.0,
                afferent_coupling=7, efferent_coupling=0,
                shared_db_density=0.0, type_export_count=10, consumer_count=7,
            ),
        }
        dashboard = compute_health_dashboard(g, metrics, [])
        rules = [o.rule for o in dashboard.observations]
        assert "stable_core" in rules

    def test_cycle_observation(self):
        g = _cycle_graph()
        metrics = _cycle_metrics()
        cycles = [CycleGroup(projects=["A", "B"], shortest_cycle=["A", "B"], edge_count=2)]
        dashboard = compute_health_dashboard(g, metrics, cycles)
        rules = [o.rule for o in dashboard.observations]
        assert "in_cycle" in rules
        # Both A and B should be flagged
        cycle_obs = [o for o in dashboard.observations if o.rule == "in_cycle"]
        assert len(cycle_obs) == 2

    def test_high_coupling_observation(self):
        """coupling_score >= 8.0 triggers high_coupling."""
        g = DependencyGraph()
        g.add_node(_make_node("Big"))
        metrics = {
            "Big": ProjectMetrics(
                fan_in=2, fan_out=3, instability=0.6, coupling_score=9.5,
                afferent_coupling=4, efferent_coupling=6,
                shared_db_density=0.0, type_export_count=5, consumer_count=2,
            ),
        }
        dashboard = compute_health_dashboard(g, metrics, [])
        rules = [o.rule for o in dashboard.observations]
        assert "high_coupling" in rules

    def test_db_hotspot_observation(self):
        """Sproc shared by 3+ projects triggers db_hotspot."""
        g = DependencyGraph()
        for name in ["P1", "P2", "P3"]:
            g.add_node(_make_node(name, sproc_references=["dbo.sp_Shared"]))
        metrics = {
            name: ProjectMetrics(
                fan_in=0, fan_out=0, instability=0.0, coupling_score=0.0,
                afferent_coupling=0, efferent_coupling=0,
                shared_db_density=0.0, type_export_count=0, consumer_count=0,
            )
            for name in ["P1", "P2", "P3"]
        }
        dashboard = compute_health_dashboard(g, metrics, [])
        rules = [o.rule for o in dashboard.observations]
        assert "db_hotspot" in rules
        assert "dbo.sp_Shared" in dashboard.db_hotspots

    def test_low_cohesion_cluster_observation(self):
        """Cluster with high coupling ratio + low cohesion triggers low_cohesion_cluster."""
        g = DependencyGraph()
        g.add_node(_make_node("X"))
        g.add_node(_make_node("Y"))
        metrics = {
            "X": ProjectMetrics(fan_in=0, fan_out=0, instability=0.0, coupling_score=0.0,
                                afferent_coupling=0, efferent_coupling=0,
                                shared_db_density=0.0, type_export_count=0, consumer_count=0),
            "Y": ProjectMetrics(fan_in=0, fan_out=0, instability=0.0, coupling_score=0.0,
                                afferent_coupling=0, efferent_coupling=0,
                                shared_db_density=0.0, type_export_count=0, consumer_count=0),
        }
        clusters = [_make_cluster("BadCluster", ["X", "Y"],
                                  coupling_to_outside=0.8, cohesion=0.1)]
        dashboard = compute_health_dashboard(g, metrics, [], clusters=clusters)
        rules = [o.rule for o in dashboard.observations]
        assert "low_cohesion_cluster" in rules

    def test_empty_graph(self):
        g = DependencyGraph()
        dashboard = compute_health_dashboard(g, {}, [])
        assert dashboard.total_projects == 0
        assert dashboard.avg_fan_in == 0.0
        assert dashboard.observations == []
        assert dashboard.max_coupling_project is None


# ===========================================================================
# TestGraphConsoleOutput
# ===========================================================================


class TestGraphConsoleOutput:
    def test_cluster_members_shown(self, capsys):
        g = _sample_graph()
        ranked = [("A", _sample_metrics()["A"])]
        clusters = [_make_cluster("TestCluster", ["A", "B", "C"])]
        print_graph_report(g, ranked, [], clusters=clusters)
        captured = capsys.readouterr().out
        assert "Members:" in captured

    def test_observations_shown(self, capsys):
        g = _sample_graph()
        ranked = [("A", _sample_metrics()["A"])]
        dashboard = HealthDashboard(
            total_projects=3, total_edges=3, total_cycles=0,
            total_clusters=0, avg_fan_in=1.0, avg_fan_out=1.0,
            avg_instability=0.5, avg_coupling_score=1.5,
            max_coupling_project="A", max_coupling_score=2.0,
            observations=[
                Observation(project="A", rule="high_coupling",
                            message="A: high coupling score (9.0)", severity="warning"),
                Observation(project="B", rule="in_cycle",
                            message="B: participates in circular dependency", severity="critical"),
            ],
        )
        print_graph_report(g, ranked, [], dashboard=dashboard)
        captured = capsys.readouterr().out
        assert "[warning]" in captured
        assert "[critical]" in captured

    def test_console_solution_count_shown(self, capsys):
        g = _sample_graph()
        g.get_node("A").solutions = ["GalaxyWorks"]
        g.get_node("B").solutions = ["GalaxyWorks"]
        ranked = [("A", _sample_metrics()["A"])]
        print_graph_report(g, ranked, [])
        captured = capsys.readouterr().out
        assert "Solutions: 1" in captured

    def test_console_solution_count_hidden_when_none(self, capsys):
        g = _sample_graph()
        # No solutions on any node
        ranked = [("A", _sample_metrics()["A"])]
        print_graph_report(g, ranked, [])
        captured = capsys.readouterr().out
        assert "Solutions:" not in captured


# ===========================================================================
# TestGraphCsvExport
# ===========================================================================


class TestGraphCsvExport:
    def test_csv_columns_and_rows(self, tmp_path):
        g = _sample_graph()
        metrics = _sample_metrics()
        out = tmp_path / "graph.csv"
        write_graph_csv_report(g, metrics, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(reader.fieldnames) == 14  # includes Solutions column
        assert len(rows) == 3  # A, B, C

    def test_csv_cluster_column(self, tmp_path):
        g = _sample_graph()
        metrics = _sample_metrics()
        clusters = [_make_cluster("MyCluster", ["A", "B"])]
        out = tmp_path / "graph.csv"
        write_graph_csv_report(g, metrics, out, clusters=clusters)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        a_row = next(r for r in rows if r["Project"] == "A")
        assert a_row["Cluster"] == "MyCluster"
        c_row = next(r for r in rows if r["Project"] == "C")
        assert c_row["Cluster"] == ""

    def test_csv_solutions_column(self, tmp_path):
        g = _sample_graph()
        # Set solutions on nodes
        g.get_node("A").solutions = ["GalaxyWorks", "Master"]
        g.get_node("B").solutions = ["GalaxyWorks"]
        # C has no solutions
        metrics = _sample_metrics()
        out = tmp_path / "graph.csv"
        write_graph_csv_report(g, metrics, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert "Solutions" in reader.fieldnames
        a_row = next(r for r in rows if r["Project"] == "A")
        assert a_row["Solutions"] == "GalaxyWorks;Master"
        b_row = next(r for r in rows if r["Project"] == "B")
        assert b_row["Solutions"] == "GalaxyWorks"
        c_row = next(r for r in rows if r["Project"] == "C")
        assert c_row["Solutions"] == ""


# ===========================================================================
# TestGraphJsonTopologyFlag
# ===========================================================================


class TestGraphCsvEdgeCases:
    def test_csv_null_namespace(self, tmp_path):
        """Projects with no namespace don't crash CSV export."""
        g = DependencyGraph()
        g.add_node(_make_node("NoNs"))  # namespace defaults to None
        metrics = {
            "NoNs": ProjectMetrics(fan_in=0, fan_out=0, instability=0.0, coupling_score=0.0,
                                   afferent_coupling=0, efferent_coupling=0,
                                   shared_db_density=0.0, type_export_count=0, consumer_count=0),
        }
        out = tmp_path / "graph.csv"
        write_graph_csv_report(g, metrics, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["Namespace"] == ""


class TestGraphJsonTopologyFlag:
    def test_includes_topology_by_default(self):
        g = _sample_graph()
        metrics = _sample_metrics()
        result = build_graph_json(g, metrics, [], [])
        assert "graph" in result

    def test_omits_topology_when_false(self):
        g = _sample_graph()
        metrics = _sample_metrics()
        result = build_graph_json(g, metrics, [], [], include_topology=False)
        assert "graph" not in result

    def test_dashboard_key_present(self):
        g = _sample_graph()
        metrics = _sample_metrics()
        dashboard = HealthDashboard(
            total_projects=3, total_edges=3, total_cycles=0,
            total_clusters=0, avg_fan_in=1.0, avg_fan_out=1.0,
            avg_instability=0.5, avg_coupling_score=1.5,
            max_coupling_project="A", max_coupling_score=2.0,
        )
        result = build_graph_json(g, metrics, [], [], dashboard=dashboard)
        assert "health_dashboard" in result
        assert result["health_dashboard"]["total_projects"] == 3

    def test_dashboard_key_absent_when_none(self):
        g = _sample_graph()
        metrics = _sample_metrics()
        result = build_graph_json(g, metrics, [], [])
        assert "health_dashboard" not in result

    def test_json_metrics_includes_solutions(self):
        g = _sample_graph()
        g.get_node("A").solutions = ["GalaxyWorks"]
        g.get_node("B").solutions = []
        metrics = _sample_metrics()
        result = build_graph_json(g, metrics, [], [])
        assert result["metrics"]["A"]["solutions"] == ["GalaxyWorks"]
        assert result["metrics"]["B"]["solutions"] == []
        assert result["metrics"]["C"]["solutions"] == []

    def test_json_topology_includes_solutions(self):
        g = _sample_graph()
        g.get_node("A").solutions = ["Sol1", "Sol2"]
        metrics = _sample_metrics()
        result = build_graph_json(g, metrics, [], [], include_topology=True)
        assert result["graph"]["nodes"]["A"]["solutions"] == ["Sol1", "Sol2"]

    def test_json_solution_metrics_section(self):
        g = _sample_graph()
        g.get_node("A").solutions = ["Sol1"]
        g.get_node("B").solutions = ["Sol1"]
        metrics = _sample_metrics()
        sol_metrics = {
            "Sol1": SolutionMetrics(
                name="Sol1", project_count=2, internal_edges=1,
                external_edges=1, cross_solution_ratio=0.5,
                incoming_solutions=[], outgoing_solutions=["Sol2"],
            ),
        }
        result = build_graph_json(
            g, metrics, [], [], solution_metrics=sol_metrics,
            bridge_projects=["A"],
        )
        assert "solution_metrics" in result
        assert result["solution_metrics"]["Sol1"]["project_count"] == 2
        assert result["solution_metrics"]["Sol1"]["cross_solution_ratio"] == 0.5
        assert result["bridge_projects"] == ["A"]

    def test_json_no_solution_metrics_when_empty(self):
        g = _sample_graph()
        metrics = _sample_metrics()
        result = build_graph_json(g, metrics, [], [])
        assert "solution_metrics" not in result
        assert "bridge_projects" not in result


class TestSolutionCouplingConsole:
    def test_console_solution_coupling_shown(self, capsys):
        g = _sample_graph()
        g.get_node("A").solutions = ["Sol1"]
        ranked = [("A", _sample_metrics()["A"])]
        sol_metrics = {
            "Sol1": SolutionMetrics(
                name="Sol1", project_count=2, internal_edges=3,
                external_edges=1, cross_solution_ratio=0.25,
                incoming_solutions=[], outgoing_solutions=[],
            ),
        }
        print_graph_report(g, ranked, [], solution_metrics=sol_metrics)
        captured = capsys.readouterr().out
        assert "Solution Coupling" in captured
        assert "Sol1" in captured

    def test_console_no_section_without_solutions(self, capsys):
        g = _sample_graph()
        ranked = [("A", _sample_metrics()["A"])]
        print_graph_report(g, ranked, [])
        captured = capsys.readouterr().out
        assert "Solution Coupling" not in captured


class TestClusterAlignmentReporters:
    def test_console_alignment_column(self, capsys):
        g = _sample_graph()
        g.get_node("A").solutions = ["Sol1"]
        g.get_node("B").solutions = ["Sol1"]
        ranked = [("A", _sample_metrics()["A"])]
        clusters = [_make_cluster("TestCluster", ["A", "B"])]
        clusters[0].solution_alignment = 1.0
        clusters[0].dominant_solution = "Sol1"
        print_graph_report(g, ranked, [], clusters=clusters)
        captured = capsys.readouterr().out
        assert "Align" in captured
        assert "1.00" in captured
        assert "(solution: Sol1)" in captured

    def test_json_cluster_alignment(self):
        g = _sample_graph()
        g.get_node("A").solutions = ["Sol1"]
        metrics = _sample_metrics()
        clusters = [_make_cluster("TestCluster", ["A", "B"])]
        clusters[0].solution_alignment = 0.75
        clusters[0].dominant_solution = "Sol1"
        result = build_graph_json(g, metrics, [], [], clusters=clusters)
        clu = result["clusters"][0]
        assert clu["solution_alignment"] == 0.75
        assert clu["dominant_solution"] == "Sol1"


# ===========================================================================
# TestMermaidFileOutput
# ===========================================================================


class TestMermaidFileOutput:
    def test_write_mermaid_to_file(self, tmp_path):
        """generate_mermaid output can be written to a file."""
        g = _sample_graph()
        out = tmp_path / "diagram.mmd"
        mermaid_output = generate_mermaid(g)
        out.write_text(mermaid_output, encoding="utf-8")
        content = out.read_text(encoding="utf-8")
        assert content.startswith("graph TD")
        assert "A --> B" in content

    def test_write_mermaid_with_clusters(self, tmp_path):
        g = _sample_graph()
        clusters = [_make_cluster("MyCluster", ["A", "B"])]
        out = tmp_path / "diagram.mmd"
        mermaid_output = generate_mermaid(g, clusters=clusters)
        out.write_text(mermaid_output, encoding="utf-8")
        content = out.read_text(encoding="utf-8")
        assert "subgraph" in content
        assert "MyCluster" in content


# ===========================================================================
# TestMermaidCLI
# ===========================================================================


class TestMermaidCLI:
    def test_non_graph_mode_rejects_mermaid_format(self):
        """Mermaid format should be rejected outside of graph mode."""
        result = subprocess.run(
            [sys.executable, "-m", "scatter",
             "--target-project", "Fake.csproj", "--search-scope", ".",
             "--output-format", "mermaid"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        assert "only supported in graph mode" in result.stderr
