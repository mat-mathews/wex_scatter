"""Regression test: parser_mode does not affect graph construction.

AST validation runs at consumer query time, not graph build time.
Both regex and hybrid modes must produce identical graphs. This test
documents that design decision — if someone re-adds AST to graph build,
this test will break and force them to justify the change.
"""

from pathlib import Path

import pytest

from scatter.config import AnalysisConfig

# Sample projects live at the repo root
SEARCH_SCOPE = Path(__file__).resolve().parents[2]


@pytest.mark.integration
class TestParserModeDoesNotAffectGraph:
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

    def test_node_count_identical(self, regex_graph, hybrid_graph):
        assert regex_graph.node_count == hybrid_graph.node_count

    def test_edge_count_identical(self, regex_graph, hybrid_graph):
        assert regex_graph.edge_count == hybrid_graph.edge_count

    def test_all_edges_identical(self, regex_graph, hybrid_graph):
        """Full edge triple comparison — catches edge swaps that count checks miss."""
        regex_edges = {(e.source, e.target, e.edge_type) for e in regex_graph.all_edges}
        hybrid_edges = {(e.source, e.target, e.edge_type) for e in hybrid_graph.all_edges}
        assert regex_edges == hybrid_edges

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
