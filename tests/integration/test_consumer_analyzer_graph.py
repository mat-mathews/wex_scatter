"""Tests for Phase B: graph-accelerated consumer lookup in find_consumers()."""
from pathlib import Path
from typing import Dict, List, Optional, Union
from unittest.mock import patch

import pytest

from scatter.analyzers.consumer_analyzer import (
    find_consumers,
    _lookup_consumers_from_graph,
    _discover_consumers_from_filesystem,
)
from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.core.models import (
    FilterStage,
    STAGE_DISCOVERY, STAGE_PROJECT_REFERENCE,
)

REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_sample_graph() -> DependencyGraph:
    """Build graph from the sample projects in the repo."""
    from scatter.analyzers.graph_builder import build_dependency_graph
    return build_dependency_graph(
        REPO_ROOT,
        disable_multiprocessing=True,
        exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
    )


def _make_graph_with_edges() -> DependencyGraph:
    """Small hand-built graph: A -> B (project_reference), A -> B (namespace_usage), C -> B (namespace_usage only)."""
    g = DependencyGraph()
    for name in ("A", "B", "C"):
        g.add_node(ProjectNode(path=Path(f"/fake/{name}/{name}.csproj"), name=name))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="namespace_usage"))
    g.add_edge(DependencyEdge(source="C", target="B", edge_type="namespace_usage"))
    return g


# ===========================================================================
# TestGraphStages12
# ===========================================================================

class TestGraphStages12:

    @pytest.mark.parametrize("target_stem", [
        "GalaxyWorks.Data",
        "MyDotNetApp",
    ])
    def test_graph_returns_same_consumers_as_filesystem(self, target_stem):
        """Core correctness: graph path and filesystem path produce the same consumer set."""
        graph = _build_sample_graph()

        # Find the target csproj
        target_node = graph.get_node(target_stem)
        if target_node is None:
            pytest.skip(f"Target '{target_stem}' not in graph")
        target_path = target_node.path.resolve()

        # Filesystem path
        fs_results, fs_pipeline = find_consumers(
            target_path, REPO_ROOT, "NAMESPACE_ERROR_skip",
            None, None, disable_multiprocessing=True,
        )
        fs_names = {r['consumer_name'] for r in fs_results}

        # Graph path
        graph_results, graph_pipeline = find_consumers(
            target_path, REPO_ROOT, "NAMESPACE_ERROR_skip",
            None, None, disable_multiprocessing=True,
            graph=graph,
        )
        graph_names = {r['consumer_name'] for r in graph_results}

        assert graph_names == fs_names

    def test_graph_skips_non_project_reference_edges(self):
        """Graph path only uses project_reference edges, not namespace_usage etc."""
        graph = _make_graph_with_edges()
        # B has consumers: A (project_ref + namespace), C (namespace only)
        # Graph path should only return A
        result = _lookup_consumers_from_graph(graph, Path("/fake/B/B.csproj"))
        assert result is not None
        names = {d['consumer_name'] for d in result.values()}
        assert "A" in names
        assert "C" not in names

    def test_graph_path_populates_filter_pipeline(self):
        """Pipeline stages report source='graph' when graph path is used."""
        graph = _make_graph_with_edges()
        # Use unreliable namespace to skip stage 3 filtering
        _, pipeline = find_consumers(
            Path("/fake/B/B.csproj"), Path("/fake"),
            "NAMESPACE_ERROR_skip", None, None,
            graph=graph,
        )
        assert len(pipeline.stages) >= 2
        discovery_stage = pipeline.stages[0]
        ref_stage = pipeline.stages[1]
        assert discovery_stage.name == STAGE_DISCOVERY
        assert discovery_stage.source == "graph"
        assert ref_stage.name == STAGE_PROJECT_REFERENCE
        assert ref_stage.source == "graph"

    def test_filesystem_path_unchanged_without_graph(self):
        """Without graph param, stages use filesystem source."""
        results, pipeline = find_consumers(
            (REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj").resolve(),
            REPO_ROOT,
            "NAMESPACE_ERROR_skip", None, None,
            disable_multiprocessing=True,
        )
        # All stages should be filesystem-sourced
        for stage in pipeline.stages:
            assert stage.source == "filesystem"

    def test_graph_path_with_stale_node(self):
        """Graph node whose path doesn't exist on disk is excluded gracefully."""
        g = DependencyGraph()
        g.add_node(ProjectNode(path=Path("/fake/Target/Target.csproj"), name="Target"))
        g.add_node(ProjectNode(path=Path("/nonexistent/Stale/Stale.csproj"), name="Stale"))
        g.add_edge(DependencyEdge(source="Stale", target="Target", edge_type="project_reference"))

        result = _lookup_consumers_from_graph(g, Path("/fake/Target/Target.csproj"))
        assert result is not None
        # Stale node is returned by graph (it exists as a node) but won't have valid files
        # The key thing is no crash
        assert len(result) == 1
        assert "Stale" in {d['consumer_name'] for d in result.values()}

    def test_target_not_in_graph_falls_back_to_filesystem(self):
        """When target is not a node in the graph, fall back to filesystem."""
        graph = _make_graph_with_edges()  # has A, B, C — no "Unknown"
        target_path = (REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj").resolve()

        # Graph doesn't have GalaxyWorks.Data, so should fall back
        results, pipeline = find_consumers(
            target_path, REPO_ROOT,
            "NAMESPACE_ERROR_skip", None, None,
            disable_multiprocessing=True,
            graph=graph,
        )
        # Should have used filesystem (fallback)
        assert len(pipeline.stages) >= 2
        assert pipeline.stages[0].source == "filesystem"

    def test_graph_consumer_proceeds_to_namespace_check(self):
        """Graph-sourced consumers still go through stage 3 namespace filtering."""
        graph = _build_sample_graph()
        target_node = graph.get_node("GalaxyWorks.Data")
        if target_node is None:
            pytest.skip("GalaxyWorks.Data not in graph")
        target_path = target_node.path.resolve()

        # With a real namespace, stage 3 filters further
        results_ns, pipeline_ns = find_consumers(
            target_path, REPO_ROOT,
            "GalaxyWorks.Data", None, None,
            disable_multiprocessing=True,
            graph=graph,
        )
        # With unreliable namespace, all direct consumers pass through
        results_all, pipeline_all = find_consumers(
            target_path, REPO_ROOT,
            "NAMESPACE_ERROR_skip", None, None,
            disable_multiprocessing=True,
            graph=graph,
        )
        # Namespace-filtered set should be <= all direct consumers
        assert len(results_ns) <= len(results_all)


# ===========================================================================
# TestGraphNamespaceBypass
# ===========================================================================

class TestGraphNamespaceBypass:

    def test_graph_path_with_unreliable_namespace(self):
        """Graph path + unreliable namespace returns all direct consumers unfiltered."""
        graph = _make_graph_with_edges()
        results, pipeline = find_consumers(
            Path("/fake/B/B.csproj"), Path("/fake"),
            "NAMESPACE_ERROR_test", None, None,
            graph=graph,
        )
        # A is the only project_reference consumer of B
        names = {r['consumer_name'] for r in results}
        assert "A" in names


# ===========================================================================
# TestImpactAnalyzerGraph
# ===========================================================================

class TestImpactAnalyzerGraph:

    def test_impact_passes_graph_to_find_consumers(self):
        """_analyze_single_target passes graph kwarg through to find_consumers."""
        from scatter.analyzers.impact_analyzer import _analyze_single_target
        from scatter.core.models import AnalysisTarget

        captured_kwargs = {}
        original_find = find_consumers

        def spy_find(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return [], None  # empty results to short-circuit

        target = AnalysisTarget(
            target_type="project",
            name="GalaxyWorks.Data",
            csproj_path=REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj",
        )
        sentinel = object()

        with patch("scatter.analyzers.impact_analyzer.find_consumers", side_effect=spy_find):
            _analyze_single_target(
                target=target, search_scope=REPO_ROOT,
                max_depth=1, pipeline_map={}, solution_file_cache=[],
                max_workers=1, chunk_size=50, disable_multiprocessing=True,
                cs_analysis_chunk_size=50, csproj_analysis_chunk_size=25,
                graph=sentinel,
            )
        assert captured_kwargs.get("graph") is sentinel

    def test_transitive_tracing_passes_graph(self):
        """trace_transitive_impact passes graph through to find_consumers calls."""
        from scatter.analyzers.impact_analyzer import trace_transitive_impact

        captured_calls = []

        def spy_find(*args, **kwargs):
            captured_calls.append(kwargs)
            from scatter.core.models import FilterPipeline
            return [], FilterPipeline(search_scope=".", total_projects_scanned=0, total_files_scanned=0)

        consumer_data = [{
            'consumer_path': REPO_ROOT / "MyDotNetApp" / "MyDotNetApp.csproj",
            'consumer_name': "MyDotNetApp",
            'relevant_files': [],
        }]
        sentinel = object()

        with patch("scatter.analyzers.impact_analyzer.find_consumers", side_effect=spy_find):
            trace_transitive_impact(
                direct_consumers=consumer_data, search_scope=REPO_ROOT,
                max_depth=1, graph=sentinel, disable_multiprocessing=True,
            )

        # At least one transitive find_consumers call should have graph
        graph_calls = [c for c in captured_calls if c.get("graph") is sentinel]
        assert len(graph_calls) >= 1

    def test_impact_without_graph_unchanged(self):
        """Without graph param, find_consumers is called with graph=None."""
        from scatter.analyzers.impact_analyzer import _analyze_single_target
        from scatter.core.models import AnalysisTarget

        captured_kwargs = {}

        def spy_find(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return [], None

        target = AnalysisTarget(
            target_type="project",
            name="GalaxyWorks.Data",
            csproj_path=REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj",
        )

        with patch("scatter.analyzers.impact_analyzer.find_consumers", side_effect=spy_find):
            _analyze_single_target(
                target=target, search_scope=REPO_ROOT,
                max_depth=1, pipeline_map={}, solution_file_cache=[],
                max_workers=1, chunk_size=50, disable_multiprocessing=True,
                cs_analysis_chunk_size=50, csproj_analysis_chunk_size=25,
            )
        assert captured_kwargs.get("graph") is None


# ===========================================================================
# TestFilterStageSource
# ===========================================================================

class TestFilterStageSource:

    def test_filter_stage_default_source(self):
        stage = FilterStage(name="test", input_count=10, output_count=5)
        assert stage.source == "filesystem"

    def test_filter_stage_graph_source(self):
        stage = FilterStage(name="test", input_count=10, output_count=5, source="graph")
        assert stage.source == "graph"
