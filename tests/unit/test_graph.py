"""Tests for Initiative 5 Phase 1: Graph model + bulk builder."""
import json
from pathlib import Path
from typing import Optional

import pytest

from scatter.core.graph import (
    MAX_EVIDENCE_ENTRIES,
    DependencyEdge,
    DependencyGraph,
    ProjectNode,
)
from scatter.scanners.project_scanner import parse_csproj_all_references

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent


def _make_node(name: str, **kwargs) -> ProjectNode:
    """Create a minimal ProjectNode for testing."""
    defaults = {
        "path": Path(f"/fake/{name}/{name}.csproj"),
        "name": name,
    }
    defaults.update(kwargs)
    return ProjectNode(**defaults)


def _sample_graph() -> DependencyGraph:
    """Build a small graph: A -> B -> C, A -> C."""
    g = DependencyGraph()
    g.add_node(_make_node("A"))
    g.add_node(_make_node("B"))
    g.add_node(_make_node("C"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="A", target="C", edge_type="namespace_usage"))
    return g


# ===========================================================================
# TestProjectNode
# ===========================================================================
class TestProjectNode:
    def test_node_construction(self):
        node = ProjectNode(
            path=Path("/foo/Bar.csproj"),
            name="Bar",
            namespace="Bar.Core",
            framework="net8.0",
            project_style="sdk",
            output_type="Library",
            file_count=5,
            type_declarations=["Foo", "Bar"],
            sproc_references=["dbo.sp_GetFoo"],
        )
        assert node.name == "Bar"
        assert node.namespace == "Bar.Core"
        assert node.framework == "net8.0"
        assert node.project_style == "sdk"
        assert node.output_type == "Library"
        assert node.file_count == 5
        assert node.type_declarations == ["Foo", "Bar"]
        assert node.sproc_references == ["dbo.sp_GetFoo"]

    def test_node_defaults(self):
        node = ProjectNode(path=Path("/x.csproj"), name="X")
        assert node.namespace is None
        assert node.framework is None
        assert node.project_style == "sdk"
        assert node.output_type is None
        assert node.file_count == 0
        assert node.type_declarations == []
        assert node.sproc_references == []

    def test_node_from_sample_project(self):
        csproj = REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        node = ProjectNode(path=csproj, name="GalaxyWorks.Data")
        assert node.name == "GalaxyWorks.Data"
        assert node.path.exists()


# ===========================================================================
# TestDependencyEdge
# ===========================================================================
class TestDependencyEdge:
    def test_edge_construction(self):
        edge = DependencyEdge(
            source="A",
            target="B",
            edge_type="project_reference",
            weight=2.0,
            evidence=["file1.cs", "file2.cs"],
            evidence_total=2,
        )
        assert edge.source == "A"
        assert edge.target == "B"
        assert edge.weight == 2.0
        assert edge.evidence == ["file1.cs", "file2.cs"]

    def test_edge_defaults(self):
        edge = DependencyEdge(source="A", target="B", edge_type="namespace_usage")
        assert edge.weight == 1.0
        assert edge.evidence is None
        assert edge.evidence_total == 0

    def test_evidence_capping(self):
        """Evidence is capped by add_edge, not by DependencyEdge itself."""
        g = DependencyGraph()
        g.add_node(_make_node("A"))
        g.add_node(_make_node("B"))
        evidence = [f"file_{i}.cs" for i in range(25)]
        edge = DependencyEdge(
            source="A",
            target="B",
            edge_type="type_usage",
            evidence=evidence,
        )
        g.add_edge(edge)

        stored = g.get_edges_from("A")[0]
        assert len(stored.evidence) == MAX_EVIDENCE_ENTRIES
        assert stored.evidence_total == 25


# ===========================================================================
# TestDependencyGraph
# ===========================================================================
class TestDependencyGraph:
    def test_empty_graph(self):
        g = DependencyGraph()
        assert g.node_count == 0
        assert g.edge_count == 0
        assert g.all_edges == []
        assert g.connected_components == []

    def test_add_node(self):
        g = DependencyGraph()
        g.add_node(_make_node("A"))
        assert g.node_count == 1
        assert g.get_node("A") is not None
        assert g.get_node("A").name == "A"

    def test_add_edge(self):
        g = _sample_graph()
        assert g.edge_count == 3
        assert len(g.get_edges_from("A")) == 2
        assert len(g.get_edges_to("C")) == 2

    def test_get_dependencies(self):
        g = _sample_graph()
        deps = g.get_dependencies("A")
        dep_names = {d.name for d in deps}
        assert dep_names == {"B", "C"}

    def test_get_consumers(self):
        g = _sample_graph()
        consumers = g.get_consumers("C")
        consumer_names = {c.name for c in consumers}
        assert consumer_names == {"A", "B"}

    def test_get_edges_from(self):
        g = _sample_graph()
        edges = g.get_edges_from("A")
        assert len(edges) == 2
        targets = {e.target for e in edges}
        assert targets == {"B", "C"}

    def test_get_edges_to(self):
        g = _sample_graph()
        edges = g.get_edges_to("C")
        assert len(edges) == 2
        sources = {e.source for e in edges}
        assert sources == {"A", "B"}

    def test_get_edges_for(self):
        g = _sample_graph()
        # B has: outgoing to C, incoming from A
        edges = g.get_edges_for("B")
        assert len(edges) == 2

    def test_get_edges_between(self):
        g = _sample_graph()
        edges = g.get_edges_between("A", "C")
        assert len(edges) == 1
        assert edges[0].edge_type == "namespace_usage"

        edges_ac = g.get_edges_between("A", "B")
        assert len(edges_ac) == 1
        assert edges_ac[0].edge_type == "project_reference"

    def test_transitive_consumers_depth_1(self):
        g = _sample_graph()
        result = g.get_transitive_consumers("C", max_depth=1)
        names = {n.name for n, d in result}
        assert names == {"A", "B"}
        for node, depth in result:
            assert depth == 1

    def test_transitive_consumers_depth_2(self):
        # D -> C -> B -> A: transitive consumers of A at depth 2
        g = DependencyGraph()
        for name in ["A", "B", "C", "D"]:
            g.add_node(_make_node(name))
        g.add_edge(DependencyEdge(source="B", target="A", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="C", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="D", target="C", edge_type="project_reference"))

        result = g.get_transitive_consumers("A", max_depth=2)
        result_map = {n.name: d for n, d in result}
        assert result_map == {"B": 1, "C": 2}

    def test_transitive_consumers_cycle_safe(self):
        g = DependencyGraph()
        for name in ["A", "B", "C"]:
            g.add_node(_make_node(name))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="C", target="A", edge_type="project_reference"))

        # Should not infinite loop. In cycle A->B->C->A:
        # Reverse edges: B<-A, C<-B, A<-C
        # Consumers of A (reverse): C at depth 1, B at depth 2 (via C<-B)
        result = g.get_transitive_consumers("A", max_depth=10)
        names = {n.name for n, _ in result}
        assert "A" not in names  # shouldn't include self
        assert names == {"B", "C"}

    def test_transitive_dependencies(self):
        g = _sample_graph()
        result = g.get_transitive_dependencies("A", max_depth=3)
        names = {n.name for n, _ in result}
        assert names == {"B", "C"}

    def test_connected_components(self):
        g = DependencyGraph()
        for name in ["A", "B", "C", "D", "E"]:
            g.add_node(_make_node(name))
        g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
        g.add_edge(DependencyEdge(source="C", target="D", edge_type="project_reference"))
        # E is isolated

        components = g.connected_components
        assert len(components) == 3
        component_sets = [set(c) for c in components]
        assert {"A", "B"} in component_sets
        assert {"C", "D"} in component_sets
        assert {"E"} in component_sets

    def test_to_dict_roundtrip(self):
        g = _sample_graph()
        data = g.to_dict()
        g2 = DependencyGraph.from_dict(data)
        assert g2.node_count == g.node_count
        assert g2.edge_count == g.edge_count

        for node in g.get_all_nodes():
            n2 = g2.get_node(node.name)
            assert n2 is not None
            assert n2.namespace == node.namespace
            assert n2.framework == node.framework

        # Verify JSON-serializable
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

    def test_duplicate_node_rejected(self):
        g = DependencyGraph()
        g.add_node(_make_node("A"))
        with pytest.raises(ValueError, match="already exists"):
            g.add_node(_make_node("A"))

    def test_edge_to_unknown_node(self):
        g = DependencyGraph()
        g.add_node(_make_node("A"))
        with pytest.raises(ValueError, match="not found"):
            g.add_edge(
                DependencyEdge(source="A", target="Z", edge_type="project_reference")
            )
        with pytest.raises(ValueError, match="not found"):
            g.add_edge(
                DependencyEdge(source="Z", target="A", edge_type="project_reference")
            )

    def test_all_edges_property(self):
        g = _sample_graph()
        edges = g.all_edges
        assert len(edges) == 3
        edge_types = {e.edge_type for e in edges}
        assert "project_reference" in edge_types
        assert "namespace_usage" in edge_types


# ===========================================================================
# TestParseCsprojAllReferences
# ===========================================================================
class TestParseCsprojAllReferences:
    def test_sdk_style_project(self):
        csproj = REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_style"] == "sdk"
        assert result["target_framework"] == "net8.0"
        assert result["project_references"] == []
        assert result["output_type"] is None  # Library is the default when not specified

    def test_framework_style_project(self):
        """MyDotNetApp.csproj is missing <Project Sdk=...> wrapper."""
        csproj = REPO_ROOT / "MyDotNetApp" / "MyDotNetApp.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_style"] == "framework"
        assert result["root_namespace"] == "MyDotNetApp"
        assert result["target_framework"] == "net8.0"
        assert result["output_type"] == "Exe"

    def test_project_with_references(self):
        csproj = REPO_ROOT / "MyDotNetApp.Consumer" / "MyDotNetApp.Consumer.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert len(result["project_references"]) == 1
        assert "MyDotNetApp.csproj" in result["project_references"][0]
        assert result["root_namespace"] == "MyDotNetApp.Consumer"

    def test_multiple_references(self):
        """Test against consumer apps that reference GalaxyWorks.Data and GalaxyWorks.Common."""
        csproj = REPO_ROOT / "MyGalaxyConsumerApp" / "MyGalaryConsumerApp.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert len(result["project_references"]) == 2
        refs_str = " ".join(result["project_references"])
        assert "GalaxyWorks.Data.csproj" in refs_str
        assert "GalaxyWorks.Common.csproj" in refs_str

    def test_missing_file(self):
        result = parse_csproj_all_references(Path("/nonexistent/fake.csproj"))
        assert result is None

    def test_no_references(self):
        csproj = REPO_ROOT / "MyDotNetApp2.Exclude" / "MyDotNetApp2.Exclude.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_references"] == []
        assert result["project_style"] == "sdk"


# ===========================================================================
# TestProjectDirectoryIndex
# ===========================================================================
class TestProjectDirectoryIndex:
    def test_build_index(self):
        from scatter.analyzers.graph_builder import _build_project_directory_index

        paths = [
            Path("/repo/ProjectA/ProjectA.csproj"),
            Path("/repo/ProjectB/ProjectB.csproj"),
        ]
        index = _build_project_directory_index(paths)
        assert len(index) == 2
        dirs = {str(d) for d in index}
        assert "/repo/ProjectA" in dirs
        assert "/repo/ProjectB" in dirs

    def test_map_cs_to_project(self):
        from scatter.analyzers.graph_builder import (
            _build_project_directory_index,
            _map_cs_to_project,
        )

        paths = [
            Path("/repo/ProjectA/ProjectA.csproj"),
            Path("/repo/ProjectB/ProjectB.csproj"),
        ]
        index = _build_project_directory_index(paths)

        assert _map_cs_to_project(Path("/repo/ProjectA/Foo.cs"), index) == "ProjectA"
        assert _map_cs_to_project(Path("/repo/ProjectB/Sub/Bar.cs"), index) == "ProjectB"
        assert _map_cs_to_project(Path("/other/Baz.cs"), index) is None

    def test_nested_projects(self):
        from scatter.analyzers.graph_builder import (
            _build_project_directory_index,
            _map_cs_to_project,
        )

        paths = [
            Path("/repo/Outer/Outer.csproj"),
            Path("/repo/Outer/Inner/Inner.csproj"),
        ]
        index = _build_project_directory_index(paths)

        # File in Inner should match Inner, not Outer
        assert _map_cs_to_project(Path("/repo/Outer/Inner/Foo.cs"), index) == "Inner"
        # File in Outer (but not Inner) should match Outer
        assert _map_cs_to_project(Path("/repo/Outer/Bar.cs"), index) == "Outer"


# ===========================================================================
# TestGraphBuilder (integration tests against sample projects)
# ===========================================================================
class TestGraphBuilder:
    @pytest.fixture(scope="class")
    def graph(self) -> DependencyGraph:
        from scatter.analyzers.graph_builder import build_dependency_graph

        return build_dependency_graph(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )

    def test_build_from_sample_projects(self, graph: DependencyGraph):
        assert graph.node_count > 0
        assert graph.edge_count > 0

    def test_node_count(self, graph: DependencyGraph):
        # 13 real .csproj files in repo (excluding temp_test_data)
        # Original 8 + GalaxyWorks.Common, GalaxyWorks.Api, GalaxyWorks.Data.Tests
        # + GalaxyWorks.DevTools, GalaxyWorks.Notifications
        assert graph.node_count == 13

    def test_expected_projects_present(self, graph: DependencyGraph):
        expected = {
            "GalaxyWorks.Data",
            "GalaxyWorks.WebPortal",
            "GalaxyWorks.BatchProcessor",
            "GalaxyWorks.Common",
            "GalaxyWorks.Api",
            "GalaxyWorks.Data.Tests",
            "GalaxyWorks.DevTools",
            "GalaxyWorks.Notifications",
            "MyDotNetApp",
            "MyDotNetApp.Consumer",
            "MyDotNetApp2.Exclude",
            "MyGalaryConsumerApp",
            "MyGalaryConsumerApp2",
        }
        actual = {n.name for n in graph.get_all_nodes()}
        assert actual == expected

    def test_project_reference_edges(self, graph: DependencyGraph):
        """There should be 14 project_reference edges."""
        ref_edges = [e for e in graph.all_edges if e.edge_type == "project_reference"]
        assert len(ref_edges) == 14

        edge_pairs = {(e.source, e.target) for e in ref_edges}
        # Original 6 edges
        assert ("MyDotNetApp.Consumer", "MyDotNetApp") in edge_pairs
        assert ("MyGalaryConsumerApp", "GalaxyWorks.Data") in edge_pairs
        assert ("MyGalaryConsumerApp2", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.WebPortal", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.BatchProcessor", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.BatchProcessor", "GalaxyWorks.WebPortal") in edge_pairs
        # New edges from added sample projects
        assert ("GalaxyWorks.Common", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Api", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Api", "GalaxyWorks.Common") in edge_pairs
        assert ("GalaxyWorks.Data.Tests", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Data.Tests", "GalaxyWorks.Common") in edge_pairs
        assert ("MyGalaryConsumerApp", "GalaxyWorks.Common") in edge_pairs
        # Hybrid AST false-positive test projects
        assert ("GalaxyWorks.DevTools", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Notifications", "GalaxyWorks.Data") in edge_pairs

    def test_galaxyworks_data_consumers(self, graph: DependencyGraph):
        consumers = graph.get_consumers("GalaxyWorks.Data")
        consumer_names = {c.name for c in consumers}
        assert "MyGalaryConsumerApp" in consumer_names
        assert "MyGalaryConsumerApp2" in consumer_names
        assert "GalaxyWorks.WebPortal" in consumer_names
        assert "GalaxyWorks.BatchProcessor" in consumer_names

    def test_mydotnetapp_consumers(self, graph: DependencyGraph):
        consumers = graph.get_consumers("MyDotNetApp")
        consumer_names = {c.name for c in consumers}
        assert "MyDotNetApp.Consumer" in consumer_names

    def test_exclude_has_zero_project_ref_edges(self, graph: DependencyGraph):
        edges = graph.get_edges_for("MyDotNetApp2.Exclude")
        ref_edges = [e for e in edges if e.edge_type == "project_reference"]
        assert len(ref_edges) == 0

    def test_namespace_extraction(self, graph: DependencyGraph):
        data_node = graph.get_node("GalaxyWorks.Data")
        assert data_node is not None
        # derive_namespace falls back to stem when no RootNamespace
        assert data_node.namespace == "GalaxyWorks.Data"

        consumer_node = graph.get_node("MyDotNetApp.Consumer")
        assert consumer_node is not None
        assert consumer_node.namespace == "MyDotNetApp.Consumer"

    def test_type_declarations_extracted(self, graph: DependencyGraph):
        data_node = graph.get_node("GalaxyWorks.Data")
        assert data_node is not None
        assert len(data_node.type_declarations) > 0
        # PortalDataService is a known class in GalaxyWorks.Data
        assert "PortalDataService" in data_node.type_declarations

    def test_file_count(self, graph: DependencyGraph):
        data_node = graph.get_node("GalaxyWorks.Data")
        assert data_node is not None
        assert data_node.file_count >= 4  # has multiple .cs files

    def test_framework_detection(self, graph: DependencyGraph):
        # MyDotNetApp has no <Project Sdk=...> wrapper → framework
        my_app = graph.get_node("MyDotNetApp")
        assert my_app is not None
        assert my_app.project_style == "framework"

        # GalaxyWorks.WebPortal uses MSBuild xmlns → framework
        portal = graph.get_node("GalaxyWorks.WebPortal")
        assert portal is not None
        assert portal.project_style == "framework"

        # GalaxyWorks.BatchProcessor uses MSBuild xmlns → framework
        batch = graph.get_node("GalaxyWorks.BatchProcessor")
        assert batch is not None
        assert batch.project_style == "framework"

        # GalaxyWorks.Data has <Project Sdk=...> → sdk
        data = graph.get_node("GalaxyWorks.Data")
        assert data is not None
        assert data.project_style == "sdk"

    def test_connected_components(self, graph: DependencyGraph):
        components = graph.connected_components
        # Should have at least 1 component; exact count depends on namespace/type edges
        assert len(components) >= 1
        # All 13 nodes should be accounted for
        total_nodes = sum(len(c) for c in components)
        assert total_nodes == 13

    def test_serialization_roundtrip(self, graph: DependencyGraph):
        data = graph.to_dict()
        g2 = DependencyGraph.from_dict(data)
        assert g2.node_count == graph.node_count
        assert g2.edge_count == graph.edge_count


# === Initiative 9 Phase 2: Solution membership on ProjectNode ===


class TestProjectNodeSolutions:
    def test_default_empty(self):
        node = _make_node("A")
        assert node.solutions == []

    def test_solutions_set(self):
        node = _make_node("A", solutions=["GalaxyWorks", "Master"])
        assert node.solutions == ["GalaxyWorks", "Master"]

    def test_to_dict_includes_solutions(self):
        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["Sol1", "Sol2"]))
        data = g.to_dict()
        assert data["nodes"]["A"]["solutions"] == ["Sol1", "Sol2"]

    def test_from_dict_with_solutions(self):
        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["Sol1"]))
        data = g.to_dict()
        g2 = DependencyGraph.from_dict(data)
        assert g2.get_node("A").solutions == ["Sol1"]

    def test_from_dict_without_solutions(self):
        """Old cache without solutions field → empty list (backward compat)."""
        data = {
            "nodes": {
                "A": {
                    "path": "/fake/A/A.csproj",
                    "name": "A",
                    "namespace": None,
                    "framework": None,
                    "project_style": "sdk",
                    "output_type": None,
                    "file_count": 0,
                    "type_declarations": [],
                    "sproc_references": [],
                    # no "solutions" key
                }
            },
            "edges": [],
        }
        g = DependencyGraph.from_dict(data)
        assert g.get_node("A").solutions == []

    def test_roundtrip_preserves_solutions(self):
        g = DependencyGraph()
        g.add_node(_make_node("A", solutions=["GalaxyWorks"]))
        g.add_node(_make_node("B", solutions=["GalaxyWorks", "Master"]))
        g.add_node(_make_node("C"))  # no solutions
        data = g.to_dict()
        g2 = DependencyGraph.from_dict(data)
        assert g2.get_node("A").solutions == ["GalaxyWorks"]
        assert g2.get_node("B").solutions == ["GalaxyWorks", "Master"]
        assert g2.get_node("C").solutions == []


class TestSolutionPopulationIntegration:
    """Integration: build graph + populate solutions from real .sln files."""

    def test_populate_from_sample_projects(self):
        from scatter.analyzers.graph_builder import build_dependency_graph
        from scatter.scanners.solution_scanner import scan_solutions, build_project_to_solutions

        repo_root = Path(__file__).parent.parent.parent
        graph = build_dependency_graph(repo_root, disable_multiprocessing=True)
        solutions = scan_solutions(repo_root)
        sol_index = build_project_to_solutions(solutions)

        # Post-process
        for node in graph.get_all_nodes():
            matches = sol_index.get(node.name, [])
            node.solutions = sorted(set(si.name for si in matches))

        # GalaxyWorks.Data should be in GalaxyWorks solution
        data_node = graph.get_node("GalaxyWorks.Data")
        assert data_node is not None
        assert "GalaxyWorks" in data_node.solutions

        # MyDotNetApp2.Exclude is also in GalaxyWorks.sln
        exclude_node = graph.get_node("MyDotNetApp2.Exclude")
        assert exclude_node is not None
        assert "GalaxyWorks" in exclude_node.solutions

    def test_populate_no_sln_files(self, tmp_path):
        """No .sln files → all nodes have empty solutions."""
        from scatter.scanners.solution_scanner import scan_solutions, build_project_to_solutions

        solutions = scan_solutions(tmp_path)
        sol_index = build_project_to_solutions(solutions)

        g = DependencyGraph()
        g.add_node(_make_node("A"))
        for node in g.get_all_nodes():
            matches = sol_index.get(node.name, [])
            node.solutions = sorted(set(si.name for si in matches))

        assert g.get_node("A").solutions == []
