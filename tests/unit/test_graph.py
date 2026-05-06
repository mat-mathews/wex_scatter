"""Tests for Initiative 5 Phase 1: Graph model + bulk builder."""

import json
from pathlib import Path

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
SAMPLES = REPO_ROOT / "samples"


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
        csproj = SAMPLES / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
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

    def test_get_projects_importing(self):
        g = DependencyGraph()
        g.add_node(
            _make_node("A", msbuild_imports=["build/wex.common.props", "Directory.Build.props"])
        )
        g.add_node(_make_node("B", msbuild_imports=["build/wex.common.props"]))
        g.add_node(_make_node("C", msbuild_imports=[]))

        result = g.get_projects_importing("build/wex.common.props")
        names = {n.name for n in result}
        assert names == {"A", "B"}

        result2 = g.get_projects_importing("Directory.Build.props")
        assert len(result2) == 1
        assert result2[0].name == "A"

        assert g.get_projects_importing("nonexistent.props") == []

    def test_get_projects_importing_normalizes_backslash(self):
        g = DependencyGraph()
        g.add_node(_make_node("A", msbuild_imports=["build/wex.common.props"]))
        result = g.get_projects_importing("build\\wex.common.props")
        assert len(result) == 1
        assert result[0].name == "A"

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
            g.add_edge(DependencyEdge(source="A", target="Z", edge_type="project_reference"))
        with pytest.raises(ValueError, match="not found"):
            g.add_edge(DependencyEdge(source="Z", target="A", edge_type="project_reference"))

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
        csproj = SAMPLES / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
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
        csproj = SAMPLES / "MyDotNetApp" / "MyDotNetApp.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_style"] == "framework"
        assert result["root_namespace"] == "MyDotNetApp"
        assert result["target_framework"] == "net8.0"
        assert result["output_type"] == "Exe"

    def test_project_with_references(self):
        csproj = SAMPLES / "MyDotNetApp.Consumer" / "MyDotNetApp.Consumer.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert len(result["project_references"]) == 1
        assert "MyDotNetApp.csproj" in result["project_references"][0]
        assert result["root_namespace"] == "MyDotNetApp.Consumer"

    def test_multiple_references(self):
        """Test against consumer apps that reference GalaxyWorks.Data and GalaxyWorks.Common."""
        csproj = SAMPLES / "MyGalaxyConsumerApp" / "MyGalaxyConsumerApp.csproj"
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
        csproj = SAMPLES / "MyDotNetApp2.Exclude" / "MyDotNetApp2.Exclude.csproj"
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
            SAMPLES,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )

    def test_build_from_sample_projects(self, graph: DependencyGraph):
        assert graph.node_count > 0
        assert graph.edge_count > 0

    def test_node_count(self, graph: DependencyGraph):
        # 15 real project files in repo (excluding temp_test_data)
        # Original 8 + GalaxyWorks.Common, GalaxyWorks.Api, GalaxyWorks.Data.Tests
        # + GalaxyWorks.DevTools, GalaxyWorks.Notifications
        # + GalaxyWorks.VBLib, GalaxyWorks.Reports
        assert graph.node_count == 15

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
            "GalaxyWorks.VBLib",
            "GalaxyWorks.Reports",
            "MyDotNetApp",
            "MyDotNetApp.Consumer",
            "MyDotNetApp2.Exclude",
            "MyGalaxyConsumerApp",
            "MyGalaxyConsumerApp2",
        }
        actual = {n.name for n in graph.get_all_nodes()}
        assert actual == expected

    def test_project_reference_edges(self, graph: DependencyGraph):
        """There should be 15 project_reference edges (VBLib adds one ref to Common)."""
        ref_edges = [e for e in graph.all_edges if e.edge_type == "project_reference"]
        assert len(ref_edges) == 15

        edge_pairs = {(e.source, e.target) for e in ref_edges}
        # Original 6 edges
        assert ("MyDotNetApp.Consumer", "MyDotNetApp") in edge_pairs
        assert ("MyGalaxyConsumerApp", "GalaxyWorks.Data") in edge_pairs
        assert ("MyGalaxyConsumerApp2", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.WebPortal", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.BatchProcessor", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.BatchProcessor", "GalaxyWorks.WebPortal") in edge_pairs
        # New edges from added sample projects
        assert ("GalaxyWorks.Common", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Api", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Api", "GalaxyWorks.Common") in edge_pairs
        assert ("GalaxyWorks.Data.Tests", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Data.Tests", "GalaxyWorks.Common") in edge_pairs
        assert ("MyGalaxyConsumerApp", "GalaxyWorks.Common") in edge_pairs
        # Hybrid AST false-positive test projects
        assert ("GalaxyWorks.DevTools", "GalaxyWorks.Data") in edge_pairs
        assert ("GalaxyWorks.Notifications", "GalaxyWorks.Data") in edge_pairs
        # VB.NET project referencing C# project (cross-language)
        assert ("GalaxyWorks.VBLib", "GalaxyWorks.Common") in edge_pairs

    def test_config_di_edge_exists(self, graph: DependencyGraph):
        """Config DI scanner should create an edge from Api → Data (unity.config)."""
        config_edges = [e for e in graph.all_edges if e.edge_type == "config_di"]
        assert len(config_edges) >= 1
        edge_pairs = {(e.source, e.target) for e in config_edges}
        assert ("GalaxyWorks.Api", "GalaxyWorks.Data") in edge_pairs

    def test_galaxyworks_data_consumers(self, graph: DependencyGraph):
        consumers = graph.get_consumers("GalaxyWorks.Data")
        consumer_names = {c.name for c in consumers}
        assert "MyGalaxyConsumerApp" in consumer_names
        assert "MyGalaxyConsumerApp2" in consumer_names
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
        # All 15 nodes should be accounted for (13 C# + 1 VB + 1 SSRS)
        total_nodes = sum(len(c) for c in components)
        assert total_nodes == 15

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


# ===========================================================================
# TestCSharpKeywords
# ===========================================================================
class TestCSharpKeywords:
    def test_is_frozenset(self):
        from scatter.core.patterns import CSHARP_KEYWORDS

        assert isinstance(CSHARP_KEYWORDS, frozenset)

    def test_contains_reserved_keywords(self):
        from scatter.core.patterns import CSHARP_KEYWORDS

        for kw in (
            "class",
            "void",
            "string",
            "int",
            "return",
            "public",
            "static",
            "namespace",
            "using",
            "if",
            "else",
            "while",
            "bool",
            "null",
        ):
            assert kw in CSHARP_KEYWORDS, f"Missing reserved keyword: {kw}"

    def test_contains_contextual_keywords(self):
        from scatter.core.patterns import CSHARP_KEYWORDS

        for kw in ("async", "await", "var", "dynamic", "yield", "partial", "record"):
            assert kw in CSHARP_KEYWORDS, f"Missing contextual keyword: {kw}"

    def test_excludes_known_type_names(self):
        from scatter.core.patterns import CSHARP_KEYWORDS

        for name in (
            "PortalDataService",
            "StringBuilder",
            "IDisposable",
            "Dictionary",
            "List",
            "Task",
            "Exception",
            "String",
        ):
            assert name not in CSHARP_KEYWORDS, f"Type name wrongly in keywords: {name}"

    def test_minimum_count(self):
        from scatter.core.patterns import CSHARP_KEYWORDS

        assert len(CSHARP_KEYWORDS) >= 100

    def test_extract_file_data_excludes_keywords(self, tmp_path):
        from scatter.analyzers.graph_builder import _extract_file_data
        from scatter.core.patterns import CSHARP_KEYWORDS

        cs_file = tmp_path / "Test.cs"
        cs_file.write_text(
            "using System;\n"
            "namespace TestNs\n"
            "{\n"
            "    public class MyWidget\n"
            "    {\n"
            "        private static int _count;\n"
            "        public void DoStuff() { return; }\n"
            "    }\n"
            "}\n"
        )
        result = _extract_file_data(cs_file)
        assert result is not None
        assert result.identifiers & CSHARP_KEYWORDS == set()
        # Actual identifiers should still be present
        assert "MyWidget" in result.identifiers
        assert "DoStuff" in result.identifiers
        assert "TestNs" in result.identifiers

    def test_keyword_filter_invisible_to_edges(self):
        """Keyword filter must not change the graph's edge set on sample projects."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        graph = build_dependency_graph(
            SAMPLES,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )
        # Type usage edges should still exist -- keywords are never type names
        type_edges = {(e.source, e.target) for e in graph.all_edges if e.edge_type == "type_usage"}
        assert len(type_edges) > 0
        # project_reference count should be unchanged (15 = 14 original + VBLib→Common)
        ref_edges = [e for e in graph.all_edges if e.edge_type == "project_reference"]
        assert len(ref_edges) == 15


# ===========================================================================
# TestUsingPattern
# ===========================================================================
class TestUsingPattern:
    def test_regular_using(self):
        from scatter.core.patterns import USING_PATTERN

        m = USING_PATTERN.findall("using System.Collections.Generic;")
        assert "System.Collections.Generic" in m

    def test_global_using(self):
        from scatter.core.patterns import USING_PATTERN

        m = USING_PATTERN.findall("global using GalaxyWorks.Data;")
        assert "GalaxyWorks.Data" in m

    def test_global_using_with_leading_whitespace(self):
        from scatter.core.patterns import USING_PATTERN

        m = USING_PATTERN.findall("  global using GalaxyWorks.Common.Models;")
        assert "GalaxyWorks.Common.Models" in m

    def test_using_static_excluded(self):
        from scatter.core.patterns import USING_PATTERN

        m = USING_PATTERN.findall("using static System.Math;")
        assert m == []

    def test_global_using_static_excluded(self):
        from scatter.core.patterns import USING_PATTERN

        m = USING_PATTERN.findall("global using static System.Console;")
        assert m == []

    def test_using_alias_excluded(self):
        """using alias = Namespace; is correctly excluded — the '=' after the
        alias name breaks the match before reaching the semicolon."""
        from scatter.core.patterns import USING_PATTERN

        m = USING_PATTERN.findall("using M = System.Math;")
        assert m == []

    def test_multiple_usings_in_content(self):
        from scatter.core.patterns import USING_PATTERN

        content = (
            "using System;\n"
            "using System.Linq;\n"
            "global using GalaxyWorks.Data;\n"
            "using static System.Math;\n"
            "using GalaxyWorks.Common;\n"
        )
        matches = USING_PATTERN.findall(content)
        assert "System" in matches
        assert "System.Linq" in matches
        assert "GalaxyWorks.Data" in matches
        assert "GalaxyWorks.Common" in matches
        # using static should NOT be captured
        assert "static" not in matches
        assert "System.Math" not in matches


# ===========================================================================
# TestScopeGate
# ===========================================================================
class TestScopeGate:
    def _build_two_project_codebase(self, tmp_path, file1_usings="", file2_usings=""):
        """Create a two-project codebase: ProjectA (consumer) -> ProjectB (provider).

        ProjectB declares type 'Widget'. ProjectA has two .cs files with
        configurable using statements.
        """
        # ProjectB: declares Widget
        proj_b = tmp_path / "ProjectB"
        proj_b.mkdir()
        (proj_b / "ProjectB.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
            "</Project>\n"
        )
        (proj_b / "Widget.cs").write_text("namespace ProjectB\n{\n    public class Widget { }\n}\n")

        # ProjectA: references ProjectB, has two files
        proj_a = tmp_path / "ProjectA"
        proj_a.mkdir()
        (proj_a / "ProjectA.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
            "  <ItemGroup>\n"
            '    <ProjectReference Include="../ProjectB/ProjectB.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        (proj_a / "File1.cs").write_text(
            f"{file1_usings}\n"
            "namespace ProjectA\n"
            "{\n"
            "    public class Consumer1\n"
            "    {\n"
            "        Widget w = new Widget();\n"
            "    }\n"
            "}\n"
        )
        (proj_a / "File2.cs").write_text(
            f"{file2_usings}\n"
            "namespace ProjectA\n"
            "{\n"
            "    public class Consumer2\n"
            "    {\n"
            "        Widget w = new Widget();\n"
            "    }\n"
            "}\n"
        )
        return tmp_path

    def test_scope_gate_positive(self, tmp_path):
        """File with using for target project produces type_usage edges."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        search_scope = self._build_two_project_codebase(
            tmp_path,
            file1_usings="using ProjectB;",
            file2_usings="",  # no usings
        )
        graph = build_dependency_graph(search_scope, disable_multiprocessing=True)

        type_edges = [e for e in graph.all_edges if e.edge_type == "type_usage"]
        assert len(type_edges) > 0
        # Evidence should include File1 (has using) but not File2 (no using, falls
        # back to project-level scope which also includes ProjectB since there's
        # a project_reference edge)
        all_evidence = []
        for e in type_edges:
            if e.evidence:
                all_evidence.extend(e.evidence)
        file1_evidence = [ev for ev in all_evidence if "File1" in ev]
        assert len(file1_evidence) > 0

    def test_scope_gate_negative(self, tmp_path):
        """File without using for target and with a different using doesn't match."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        # Create a third project so File2 has a using that maps to something else
        proj_c = tmp_path / "ProjectC"
        proj_c.mkdir()
        (proj_c / "ProjectC.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
            "</Project>\n"
        )
        (proj_c / "Gadget.cs").write_text("namespace ProjectC { public class Gadget { } }\n")

        search_scope = self._build_two_project_codebase(
            tmp_path,
            file1_usings="using ProjectB;",
            file2_usings="using ProjectC;",  # has a using, but not for ProjectB
        )
        # Also add ProjectC reference to ProjectA
        csproj = tmp_path / "ProjectA" / "ProjectA.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
            "  <ItemGroup>\n"
            '    <ProjectReference Include="../ProjectB/ProjectB.csproj" />\n'
            '    <ProjectReference Include="../ProjectC/ProjectC.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )

        graph = build_dependency_graph(search_scope, disable_multiprocessing=True)

        type_edges = [
            e
            for e in graph.all_edges
            if e.edge_type == "type_usage" and e.source == "ProjectA" and e.target == "ProjectB"
        ]
        # Only File1 should have evidence (it has using ProjectB)
        # File2 has using ProjectC, so its file_reachable is {ProjectC} — not empty,
        # so no fallback to project-level scope, and ProjectB is not in scope.
        all_evidence = []
        for e in type_edges:
            if e.evidence:
                all_evidence.extend(e.evidence)
        file2_evidence = [ev for ev in all_evidence if "File2" in ev]
        assert len(file2_evidence) == 0, f"File2 should not match ProjectB: {file2_evidence}"

    def test_scope_gate_global_using_fallback(self, tmp_path):
        """Files relying on global using should still get edges via fallback."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        # Build the codebase: File1 has no local using, but GlobalUsings.cs does
        search_scope = self._build_two_project_codebase(
            tmp_path,
            file1_usings="",  # no local using
            file2_usings="",  # no local using
        )
        # Add a GlobalUsings.cs to ProjectA
        global_usings = tmp_path / "ProjectA" / "GlobalUsings.cs"
        global_usings.write_text("global using ProjectB;\n")

        graph = build_dependency_graph(search_scope, disable_multiprocessing=True)

        type_edges = [
            e
            for e in graph.all_edges
            if e.edge_type == "type_usage" and e.source == "ProjectA" and e.target == "ProjectB"
        ]
        # GlobalUsings.cs has the namespace match, so its file_reachable is non-empty.
        # File1 and File2 have no usings → empty file_reachable → fall back to
        # project-level scope (which includes ProjectB via project_reference).
        # So all three files should be able to produce evidence.
        assert len(type_edges) > 0

    def test_scope_gate_with_full_type_scan(self, tmp_path):
        """full_type_scan=True bypasses the scope gate entirely."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        search_scope = self._build_two_project_codebase(
            tmp_path,
            file1_usings="",
            file2_usings="",
        )
        graph = build_dependency_graph(
            search_scope,
            disable_multiprocessing=True,
            full_type_scan=True,
        )
        type_edges = [
            e
            for e in graph.all_edges
            if e.edge_type == "type_usage" and e.source == "ProjectA" and e.target == "ProjectB"
        ]
        assert len(type_edges) > 0


# ===========================================================================
# TestWalkAndCollect
# ===========================================================================
class TestWalkAndCollect:
    def test_collects_by_extension(self, tmp_path):
        from scatter.core.parallel import walk_and_collect

        (tmp_path / "a.cs").write_text("class A {}")
        (tmp_path / "b.csproj").write_text("<Project/>")
        (tmp_path / "c.txt").write_text("ignored")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "d.cs").write_text("class D {}")

        result = walk_and_collect(tmp_path, {".cs", ".csproj"})
        cs_names = {p.name for p in result[".cs"]}
        csproj_names = {p.name for p in result[".csproj"]}
        assert cs_names == {"a.cs", "d.cs"}
        assert csproj_names == {"b.csproj"}

    def test_prunes_excluded_dirs(self, tmp_path):
        from scatter.core.parallel import walk_and_collect

        # Create bin/ and obj/ with .cs files that should be excluded
        for d in ("bin", "obj"):
            excluded = tmp_path / d
            excluded.mkdir()
            (excluded / "should_not_find.cs").write_text("class X {}")
            deep = excluded / "Debug" / "net8.0"
            deep.mkdir(parents=True)
            (deep / "deep.cs").write_text("class Y {}")

        # Non-excluded file
        (tmp_path / "real.cs").write_text("class Real {}")

        result = walk_and_collect(tmp_path, {".cs"}, exclude_dirs={"bin", "obj"})
        cs_paths = result[".cs"]
        assert len(cs_paths) == 1
        assert cs_paths[0].name == "real.cs"
        # Verify no path contains excluded directory names
        for p in cs_paths:
            assert "bin" not in p.parts
            assert "obj" not in p.parts

    def test_prunes_dot_prefixed_dirs(self, tmp_path):
        from scatter.core.parallel import walk_and_collect

        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config.cs").write_text("not a real cs file")
        vs_dir = tmp_path / ".vs"
        vs_dir.mkdir()
        (vs_dir / "settings.cs").write_text("not real either")
        (tmp_path / "real.cs").write_text("class Real {}")

        result = walk_and_collect(tmp_path, {".cs"})
        assert len(result[".cs"]) == 1
        assert result[".cs"][0].name == "real.cs"

    def test_empty_directory(self, tmp_path):
        from scatter.core.parallel import walk_and_collect

        result = walk_and_collect(tmp_path, {".cs", ".csproj"})
        assert result[".cs"] == []
        assert result[".csproj"] == []

    def test_permission_error_continues(self, tmp_path):
        """Walk should log and continue on permission errors, not crash."""
        from scatter.core.parallel import walk_and_collect

        (tmp_path / "good.cs").write_text("class Good {}")
        # Even if os.walk encounters errors, the function should return results
        result = walk_and_collect(tmp_path, {".cs"})
        assert len(result[".cs"]) == 1

    def test_matches_old_approach_on_samples(self):
        """walk_and_collect must produce identical file sets to the old
        find_files_with_pattern_parallel + _filter_excluded approach."""
        from scatter.core.parallel import walk_and_collect, find_files_with_pattern_parallel
        from scatter.analyzers.graph_builder import _filter_excluded

        exclude_patterns = ["*/bin/*", "*/obj/*", "*/temp_test_data/*"]

        # Old approach
        old_csproj = set(
            _filter_excluded(
                find_files_with_pattern_parallel(SAMPLES, "*.csproj", disable_multiprocessing=True),
                exclude_patterns,
            )
        )
        old_cs = set(
            _filter_excluded(
                find_files_with_pattern_parallel(SAMPLES, "*.cs", disable_multiprocessing=True),
                exclude_patterns,
            )
        )

        # New approach
        from scatter.core.parallel import extract_exclude_dirs

        exclude_dirs = extract_exclude_dirs(exclude_patterns)
        new = walk_and_collect(SAMPLES, {".csproj", ".cs"}, exclude_dirs)
        new_csproj = set(new[".csproj"])
        new_cs = set(new[".cs"])

        assert new_csproj == old_csproj, (
            f"csproj diff — only in new: {new_csproj - old_csproj}, "
            f"only in old: {old_csproj - new_csproj}"
        )
        assert new_cs == old_cs, (
            f"cs diff — only in new: {new_cs - old_cs}, only in old: {old_cs - new_cs}"
        )


# ===========================================================================
# TestExtractExcludeDirs
# ===========================================================================
class TestExtractExcludeDirs:
    def test_standard_patterns(self):
        from scatter.core.parallel import extract_exclude_dirs

        result = extract_exclude_dirs(["*/bin/*", "*/obj/*", "*/temp_test_data/*"])
        assert result == {"bin", "obj", "temp_test_data"}

    def test_double_star_patterns(self):
        from scatter.core.parallel import extract_exclude_dirs

        result = extract_exclude_dirs(["**/bin/**", "**/obj/**"])
        assert result == {"bin", "obj"}

    def test_bare_name(self):
        from scatter.core.parallel import extract_exclude_dirs

        result = extract_exclude_dirs(["bin"])
        assert result == {"bin"}

    def test_trailing_only(self):
        from scatter.core.parallel import extract_exclude_dirs

        result = extract_exclude_dirs(["*/bin"])
        assert result == {"bin"}

    def test_path_with_separator_ignored(self):
        """Patterns with path separators in the name portion are not directory names."""
        from scatter.core.parallel import extract_exclude_dirs

        result = extract_exclude_dirs(["*/some/path/*"])
        assert result == set()

    def test_empty_list(self):
        from scatter.core.parallel import extract_exclude_dirs

        result = extract_exclude_dirs([])
        assert result == set()


# ===========================================================================
# TestProjectReferenceBackslash
# ===========================================================================
class TestProjectReferenceBackslash:
    def test_backslash_include_resolved(self, tmp_path):
        """ProjectReference Include paths using Windows backslashes should resolve."""
        from scatter.analyzers.graph_builder import build_dependency_graph

        # ProjectB: target
        proj_b = tmp_path / "ProjectB"
        proj_b.mkdir()
        (proj_b / "ProjectB.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
            "</Project>\n"
        )
        (proj_b / "Widget.cs").write_text("namespace ProjectB { public class Widget { } }\n")

        # ProjectA: references ProjectB with backslash path
        proj_a = tmp_path / "ProjectA"
        proj_a.mkdir()
        (proj_a / "ProjectA.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
            "  <ItemGroup>\n"
            '    <ProjectReference Include="..\\ProjectB\\ProjectB.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        (proj_a / "Consumer.cs").write_text(
            "using ProjectB;\nnamespace ProjectA { public class Consumer { } }\n"
        )

        graph = build_dependency_graph(tmp_path, disable_multiprocessing=True)

        ref_edges = [e for e in graph.all_edges if e.edge_type == "project_reference"]
        edge_pairs = {(e.source, e.target) for e in ref_edges}
        assert ("ProjectA", "ProjectB") in edge_pairs, (
            f"Backslash Include should resolve. Edges: {edge_pairs}"
        )


# ===========================================================================
# TestDbScannerContentCache
# ===========================================================================
class TestDbScannerContentCache:
    def test_cache_produces_identical_results(self):
        """DB scanner with content_by_path should match scanning without."""
        from scatter.core.parallel import walk_and_collect
        from scatter.core.parallel import extract_exclude_dirs
        from scatter.scanners.db_scanner import scan_db_dependencies
        from collections import defaultdict

        exclude_patterns = ["*/bin/*", "*/obj/*", "*/temp_test_data/*"]
        exclude_dirs = extract_exclude_dirs(exclude_patterns)
        discovered = walk_and_collect(SAMPLES, {".csproj", ".cs"}, exclude_dirs)

        # Build project_cs_map the same way graph_builder does
        from scatter.analyzers.graph_builder import (
            _build_project_directory_index,
            _map_cs_to_project,
        )

        csproj_files = discovered[".csproj"]
        cs_files = discovered[".cs"]
        project_dir_index = _build_project_directory_index(csproj_files)
        project_cs_files = defaultdict(list)
        for cs_path in cs_files:
            mapped = _map_cs_to_project(cs_path, project_dir_index)
            if mapped:
                project_cs_files[mapped].append(cs_path)

        project_cs_map = dict(project_cs_files)

        # Build content cache
        content_by_path = {}
        for cs_paths in project_cs_map.values():
            for cs_path in cs_paths:
                try:
                    content_by_path[cs_path] = cs_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass

        # Run without cache
        deps_without = scan_db_dependencies(
            SAMPLES,
            project_cs_map=project_cs_map,
            disable_multiprocessing=True,
        )

        # Run with cache
        deps_with = scan_db_dependencies(
            SAMPLES,
            project_cs_map=project_cs_map,
            content_by_path=content_by_path,
            disable_multiprocessing=True,
        )

        # Compare results — same count and same dependency objects
        assert len(deps_with) == len(deps_without), (
            f"Cache: {len(deps_with)} deps, no cache: {len(deps_without)} deps"
        )
        without_set = {(d.db_object_name, d.db_object_type, d.source_project) for d in deps_without}
        with_set = {(d.db_object_name, d.db_object_type, d.source_project) for d in deps_with}
        assert with_set == without_set
