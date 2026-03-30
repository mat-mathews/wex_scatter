"""Regression test: hybrid mode must produce <= edges compared to regex mode.

Builds the dependency graph on the sample projects in both regex and hybrid
modes, then asserts hybrid never introduces edges that regex didn't find.
"""

from pathlib import Path

import pytest

from scatter.config import AnalysisConfig

# Sample projects live at the repo root
SEARCH_SCOPE = Path(__file__).resolve().parents[2]


@pytest.mark.integration
class TestHybridRegression:
    @pytest.fixture(scope="class")
    def regex_graph(self):
        from scatter.analyzers.graph_builder import build_dependency_graph

        return build_dependency_graph(
            SEARCH_SCOPE,
            disable_multiprocessing=True,
            analysis_config=AnalysisConfig(parser_mode="regex"),
        )

    @pytest.fixture(scope="class")
    def hybrid_graph(self):
        from scatter.analyzers.graph_builder import build_dependency_graph

        return build_dependency_graph(
            SEARCH_SCOPE,
            disable_multiprocessing=True,
            analysis_config=AnalysisConfig(parser_mode="hybrid"),
        )

    def test_hybrid_edge_count_lte_regex(self, regex_graph, hybrid_graph):
        """Hybrid mode should produce the same or fewer total edges."""
        delta = regex_graph.edge_count - hybrid_graph.edge_count
        print(
            f"\n  Edge count — regex: {regex_graph.edge_count}, "
            f"hybrid: {hybrid_graph.edge_count}, delta: {delta}"
        )
        assert hybrid_graph.edge_count <= regex_graph.edge_count

    def test_project_reference_edges_identical(self, regex_graph, hybrid_graph):
        """AST validation doesn't affect XML-based project_reference edges."""
        regex_pr = {
            (e.source, e.target)
            for e in regex_graph.all_edges
            if e.edge_type == "project_reference"
        }
        hybrid_pr = {
            (e.source, e.target)
            for e in hybrid_graph.all_edges
            if e.edge_type == "project_reference"
        }
        assert regex_pr == hybrid_pr

    def test_namespace_usage_edges_identical(self, regex_graph, hybrid_graph):
        """AST validation doesn't affect namespace_usage edges in the spike."""
        regex_ns = {
            (e.source, e.target) for e in regex_graph.all_edges if e.edge_type == "namespace_usage"
        }
        hybrid_ns = {
            (e.source, e.target) for e in hybrid_graph.all_edges if e.edge_type == "namespace_usage"
        }
        assert regex_ns == hybrid_ns

    def test_type_usage_edges_subset(self, regex_graph, hybrid_graph):
        """Hybrid type_usage edges are a subset of regex type_usage edges."""
        regex_tu = {
            (e.source, e.target) for e in regex_graph.all_edges if e.edge_type == "type_usage"
        }
        hybrid_tu = {
            (e.source, e.target) for e in hybrid_graph.all_edges if e.edge_type == "type_usage"
        }
        eliminated = regex_tu - hybrid_tu
        if eliminated:
            print(f"\n  type_usage edges eliminated by hybrid: {eliminated}")
        print(
            f"\n  type_usage — regex: {len(regex_tu)}, hybrid: {len(hybrid_tu)}, "
            f"eliminated: {len(eliminated)}"
        )
        assert hybrid_tu <= regex_tu
