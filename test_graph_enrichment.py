"""Tests for graph metrics enrichment in legacy and impact modes."""
import csv
import json
from io import StringIO
from pathlib import Path
from typing import Dict, List

import pytest

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.core.models import EnrichedConsumer
from scatter.analyzers.coupling_analyzer import (
    CycleGroup,
    ProjectMetrics,
    compute_all_metrics,
    detect_cycles,
)
from scatter.analyzers.graph_enrichment import (
    GraphContext,
    enrich_consumers,
    enrich_legacy_results,
)
from scatter.reports.json_reporter import prepare_detailed_results
from scatter.reports.csv_reporter import write_csv_report
from scatter.reports.markdown_reporter import build_markdown, build_impact_markdown
from scatter.reports.console_reporter import print_console_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph() -> DependencyGraph:
    """A -> B -> C chain with a B <-> C cycle."""
    g = DependencyGraph()
    for name in ("A", "B", "C"):
        g.add_node(ProjectNode(path=Path(f"/repo/{name}/{name}.csproj"), name=name))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="C", target="B", edge_type="project_reference"))  # cycle
    return g


def _make_graph_context() -> GraphContext:
    graph = _make_graph()
    metrics = compute_all_metrics(graph)
    cycles = detect_cycles(graph)
    cycle_members = set()
    for cg in cycles:
        cycle_members.update(cg.projects)
    return GraphContext(graph=graph, metrics=metrics, cycles=cycles, cycle_members=cycle_members)


def _make_result(consumer_name: str) -> Dict:
    return {
        "TargetProjectName": "Target",
        "TargetProjectPath": "Target/Target.csproj",
        "TriggeringType": "SomeClass",
        "ConsumerProjectName": consumer_name,
        "ConsumerProjectPath": f"{consumer_name}/{consumer_name}.csproj",
        "ConsumingSolutions": [],
        "PipelineName": None,
        "BatchJobVerification": None,
        "ConsumerFileSummaries": {},
    }


def _make_enriched_consumer(name: str) -> EnrichedConsumer:
    return EnrichedConsumer(
        consumer_path=Path(f"/repo/{name}/{name}.csproj"),
        consumer_name=name,
    )


# ---------------------------------------------------------------------------
# GraphContext construction
# ---------------------------------------------------------------------------

class TestGraphContext:

    def test_cycle_members_populated(self):
        ctx = _make_graph_context()
        assert "B" in ctx.cycle_members
        assert "C" in ctx.cycle_members
        assert "A" not in ctx.cycle_members

    def test_metrics_populated(self):
        ctx = _make_graph_context()
        assert "A" in ctx.metrics
        assert "B" in ctx.metrics
        assert "C" in ctx.metrics
        assert ctx.metrics["A"].fan_out == 1
        assert ctx.metrics["B"].fan_in >= 1


# ---------------------------------------------------------------------------
# enrich_legacy_results
# ---------------------------------------------------------------------------

class TestEnrichLegacyResults:

    def test_metrics_injected(self):
        ctx = _make_graph_context()
        results = [_make_result("B")]
        enrich_legacy_results(results, ctx)

        assert results[0]["CouplingScore"] is not None
        assert results[0]["FanIn"] is not None
        assert results[0]["FanOut"] is not None
        assert results[0]["Instability"] is not None
        assert results[0]["InCycle"] is True

    def test_non_cycle_member(self):
        ctx = _make_graph_context()
        results = [_make_result("A")]
        enrich_legacy_results(results, ctx)

        assert results[0]["InCycle"] is False

    def test_unknown_consumer(self):
        ctx = _make_graph_context()
        results = [_make_result("Unknown")]
        enrich_legacy_results(results, ctx)

        assert results[0]["CouplingScore"] is None
        assert results[0]["FanIn"] is None
        assert results[0]["InCycle"] is None

    def test_idempotent(self):
        ctx = _make_graph_context()
        results = [_make_result("B")]
        enrich_legacy_results(results, ctx)
        score_first = results[0]["CouplingScore"]
        enrich_legacy_results(results, ctx)
        assert results[0]["CouplingScore"] == score_first


# ---------------------------------------------------------------------------
# enrich_consumers
# ---------------------------------------------------------------------------

class TestEnrichConsumers:

    def test_fields_populated(self):
        ctx = _make_graph_context()
        consumers = [_make_enriched_consumer("B")]
        enrich_consumers(consumers, ctx)

        assert consumers[0].coupling_score is not None
        assert consumers[0].fan_in is not None
        assert consumers[0].fan_out is not None
        assert consumers[0].instability is not None
        assert consumers[0].in_cycle is True

    def test_unknown_stays_none(self):
        ctx = _make_graph_context()
        consumers = [_make_enriched_consumer("Unknown")]
        enrich_consumers(consumers, ctx)

        assert consumers[0].coupling_score is None
        assert consumers[0].in_cycle is None


# ---------------------------------------------------------------------------
# Reporter regression: "no graph" path unchanged
# ---------------------------------------------------------------------------

class TestNoGraphRegression:
    """When --graph-metrics is NOT passed, output must be identical to pre-change."""

    def test_console_no_graph(self, capsys):
        results = [_make_result("B")]
        print_console_report(results, graph_metrics_requested=False)
        output = capsys.readouterr().out
        assert "Graph:" not in output
        assert "coupling=" not in output

    def test_json_no_graph(self):
        results = [_make_result("B")]
        detailed = prepare_detailed_results(results, graph_metrics_requested=False)
        assert "CouplingScore" not in detailed[0]
        assert "FanIn" not in detailed[0]

    def test_csv_no_graph(self, tmp_path):
        results = [_make_result("B")]
        out_file = tmp_path / "out.csv"
        write_csv_report(results, out_file, graph_metrics_requested=False)
        header = out_file.read_text().splitlines()[0]
        assert "CouplingScore" not in header
        assert "FanIn" not in header

    def test_markdown_no_graph(self):
        results = [_make_result("B")]
        md = build_markdown(results, graph_metrics_requested=False)
        assert "Coupling" not in md
        assert "Fan-In" not in md


# ---------------------------------------------------------------------------
# Reporter: schema stability when flag is on
# ---------------------------------------------------------------------------

class TestSchemaWithGraphMetrics:
    """When --graph-metrics IS passed, schema includes graph columns even for unmatched."""

    def test_json_keys_present_for_unmatched(self):
        results = [_make_result("Unknown")]
        detailed = prepare_detailed_results(results, graph_metrics_requested=True)
        assert "CouplingScore" in detailed[0]
        assert detailed[0]["CouplingScore"] is None
        assert "FanIn" in detailed[0]
        assert "InCycle" in detailed[0]

    def test_csv_columns_present_for_unmatched(self, tmp_path):
        results = [_make_result("Unknown")]
        out_file = tmp_path / "out.csv"
        write_csv_report(results, out_file, graph_metrics_requested=True)
        lines = out_file.read_text().splitlines()
        header = lines[0]
        assert "CouplingScore" in header
        assert "FanIn" in header
        assert "InCycle" in header

    def test_json_keys_present_with_enriched_data(self):
        ctx = _make_graph_context()
        results = [_make_result("B")]
        enrich_legacy_results(results, ctx)
        detailed = prepare_detailed_results(results, graph_metrics_requested=True)
        assert detailed[0]["CouplingScore"] is not None
        assert detailed[0]["InCycle"] is True

    def test_markdown_columns_present(self):
        ctx = _make_graph_context()
        results = [_make_result("B")]
        enrich_legacy_results(results, ctx)
        md = build_markdown(results, graph_metrics_requested=True)
        assert "Coupling" in md
        assert "Fan-In" in md
        assert "Instability" in md

    def test_console_shows_graph_line(self, capsys):
        ctx = _make_graph_context()
        results = [_make_result("B")]
        enrich_legacy_results(results, ctx)
        print_console_report(results, graph_metrics_requested=True)
        output = capsys.readouterr().out
        assert "Graph: coupling=" in output
        assert "in-cycle=yes" in output
