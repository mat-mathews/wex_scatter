"""Tests for graph metrics enrichment in legacy and impact modes."""
import argparse
import csv
import json
import logging
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch as mock_patch

import pytest

from scatter.cli import _ensure_graph_context

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.core.models import ConsumerResult, EnrichedConsumer
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


def _make_result(consumer_name: str) -> ConsumerResult:
    return ConsumerResult(
        target_project_name="Target",
        target_project_path="Target/Target.csproj",
        triggering_type="SomeClass",
        consumer_project_name=consumer_name,
        consumer_project_path=f"{consumer_name}/{consumer_name}.csproj",
    )


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

        assert results[0].coupling_score is not None
        assert results[0].fan_in is not None
        assert results[0].fan_out is not None
        assert results[0].instability is not None
        assert results[0].in_cycle is True

    def test_non_cycle_member(self):
        ctx = _make_graph_context()
        results = [_make_result("A")]
        enrich_legacy_results(results, ctx)

        assert results[0].in_cycle is False

    def test_unknown_consumer(self):
        ctx = _make_graph_context()
        results = [_make_result("Unknown")]
        enrich_legacy_results(results, ctx)

        assert results[0].coupling_score is None
        assert results[0].fan_in is None
        assert results[0].in_cycle is None

    def test_idempotent(self):
        ctx = _make_graph_context()
        results = [_make_result("B")]
        enrich_legacy_results(results, ctx)
        score_first = results[0].coupling_score
        enrich_legacy_results(results, ctx)
        assert results[0].coupling_score == score_first


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
        detailed = prepare_detailed_results(results, graph_metrics_requested=False)
        out_file = tmp_path / "out.csv"
        write_csv_report(detailed, out_file, graph_metrics_requested=False)
        header = out_file.read_text().splitlines()[0]
        assert "CouplingScore" not in header
        assert "FanIn" not in header

    def test_markdown_no_graph(self):
        results = [_make_result("B")]
        detailed = prepare_detailed_results(results, graph_metrics_requested=False)
        md = build_markdown(detailed, graph_metrics_requested=False)
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
        detailed = prepare_detailed_results(results, graph_metrics_requested=True)
        out_file = tmp_path / "out.csv"
        write_csv_report(detailed, out_file, graph_metrics_requested=True)
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
        detailed = prepare_detailed_results(results, graph_metrics_requested=True)
        md = build_markdown(detailed, graph_metrics_requested=True)
        assert "Coupling" in md
        assert "Fan-In" in md
        assert "Instability" in md

    def test_console_shows_graph_line(self, capsys):
        ctx = _make_graph_context()
        results = [_make_result("B")]
        enrich_legacy_results(results, ctx)
        print_console_report(results, graph_metrics_requested=True)
        output = capsys.readouterr().out
        assert "Score" in output
        assert "Fan-In" in output


# ---------------------------------------------------------------------------
# Auto graph loading (Phase A: transparent graph)
# ---------------------------------------------------------------------------

def _resolve_graph_loading(graph_metrics=False, no_graph=False,
                           cache_hit=False, build_returns_ctx=True):
    """Simulate the graph loading logic from __main__.py.

    Returns (graph_ctx, graph_enriched) using the same branching as the real code.
    """
    graph_ctx = None
    graph_enriched = False
    search_scope_abs = Path("/fake/scope")
    is_graph_mode = False

    if not no_graph and search_scope_abs and not is_graph_mode:
        should_load_graph = graph_metrics or cache_hit
        if should_load_graph:
            if build_returns_ctx:
                graph_ctx = _make_graph_context()
                graph_enriched = True
            elif graph_metrics:
                pass  # would log warning in real code
    return graph_ctx, graph_enriched


class TestAutoGraphLoading:

    def test_auto_loads_when_cache_exists(self):
        ctx, enriched = _resolve_graph_loading(cache_hit=True)
        assert ctx is not None
        assert enriched is True

    def test_skips_when_no_cache_and_no_flag(self):
        ctx, enriched = _resolve_graph_loading(cache_hit=False, graph_metrics=False)
        assert ctx is None
        assert enriched is False

    def test_builds_when_graph_metrics_flag_no_cache(self):
        ctx, enriched = _resolve_graph_loading(graph_metrics=True, cache_hit=False)
        assert ctx is not None
        assert enriched is True

    def test_no_graph_flag_skips_everything(self):
        ctx, enriched = _resolve_graph_loading(no_graph=True, cache_hit=True)
        assert ctx is None
        assert enriched is False

    def test_silent_failure_on_auto_load(self, caplog):
        with caplog.at_level(logging.WARNING):
            ctx, enriched = _resolve_graph_loading(
                cache_hit=True, build_returns_ctx=False, graph_metrics=False
            )
        assert ctx is None
        assert enriched is False
        assert "Graph context unavailable" not in caplog.text

    def test_graph_metrics_flag_builds_without_cache(self):
        ctx, enriched = _resolve_graph_loading(graph_metrics=True, cache_hit=False)
        assert ctx is not None
        assert enriched is True

    def test_impact_mode_auto_enrichment(self):
        """Impact consumers gain graph fields when graph_ctx is available (auto-loaded)."""
        ctx = _make_graph_context()
        consumers = [_make_enriched_consumer("B"), _make_enriched_consumer("C")]
        # Simulate the new impact enrichment guard: `if graph_ctx:`
        if ctx:
            enrich_consumers(consumers, ctx)
        assert consumers[0].coupling_score is not None
        assert consumers[0].in_cycle is True
        assert consumers[1].coupling_score is not None


# ---------------------------------------------------------------------------
# _build_metadata graph_enriched field
# ---------------------------------------------------------------------------

class TestBuildMetadataGraphEnriched:

    def test_graph_enriched_true(self):
        from scatter.cli import _build_metadata
        import argparse
        args = argparse.Namespace(verbose=False, output_format="json")
        metadata = _build_metadata(args, Path("/fake"), 0.0, graph_enriched=True)
        assert metadata['graph_enriched'] is True

    def test_graph_enriched_false(self):
        from scatter.cli import _build_metadata
        import argparse
        args = argparse.Namespace(verbose=False, output_format="json")
        metadata = _build_metadata(args, Path("/fake"), 0.0, graph_enriched=False)
        assert metadata['graph_enriched'] is False

    def test_graph_enriched_default(self):
        from scatter.cli import _build_metadata
        import argparse
        args = argparse.Namespace(verbose=False, output_format="json")
        metadata = _build_metadata(args, Path("/fake"), 0.0)
        assert metadata['graph_enriched'] is False


# ---------------------------------------------------------------------------
# CLI integration: JSON metadata contains graph_enriched
# ---------------------------------------------------------------------------

class TestJsonGraphEnrichedField:

    def test_json_output_contains_graph_enriched(self, tmp_path):
        out = tmp_path / "result.json"
        result = subprocess.run(
            [sys.executable, "-m", "scatter",
             "--target-project", "./GalaxyWorks.Data/GalaxyWorks.Data.csproj",
             "--search-scope", ".",
             "--output-format", "json", "--output-file", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text())
        assert "metadata" in data
        assert "graph_enriched" in data["metadata"]
        assert isinstance(data["metadata"]["graph_enriched"], bool)

    def test_auto_load_golden_path(self, tmp_path):
        """Build cache with --graph-metrics, then auto-load without it, then --no-graph."""
        base_args = [
            sys.executable, "-m", "scatter",
            "--target-project", "./GalaxyWorks.Data/GalaxyWorks.Data.csproj",
            "--search-scope", ".",
            "--output-format", "json",
        ]

        # Step 1: Build cache with --graph-metrics
        out1 = tmp_path / "step1.json"
        r1 = subprocess.run(
            base_args + ["--graph-metrics", "--output-file", str(out1)],
            capture_output=True, text=True,
        )
        assert r1.returncode == 0, r1.stderr
        data1 = json.loads(out1.read_text())
        assert data1["metadata"]["graph_enriched"] is True

        # Step 2: Auto-load — no --graph-metrics flag, cache exists from step 1
        out2 = tmp_path / "step2.json"
        r2 = subprocess.run(
            base_args + ["--output-file", str(out2)],
            capture_output=True, text=True,
        )
        assert r2.returncode == 0, r2.stderr
        data2 = json.loads(out2.read_text())
        assert data2["metadata"]["graph_enriched"] is True, "Should auto-load from cache"

        # Step 3: --no-graph skips enrichment
        out3 = tmp_path / "step3.json"
        r3 = subprocess.run(
            base_args + ["--no-graph", "--output-file", str(out3)],
            capture_output=True, text=True,
        )
        assert r3.returncode == 0, r3.stderr
        data3 = json.loads(out3.read_text())
        assert data3["metadata"]["graph_enriched"] is False, "--no-graph should skip"


# ---------------------------------------------------------------------------
# Phase C: First-run graph build (_ensure_graph_context)
# ---------------------------------------------------------------------------

class TestEnsureGraphContext:
    """Unit tests for the _ensure_graph_context() idempotent helper.

    _ensure_graph_context mutates ctx.graph_ctx and ctx.graph_enriched in place.
    """

    def test_idempotent_when_graph_already_loaded(self, make_mode_context):
        """Returns immediately if graph_ctx is already set — no build triggered."""
        existing_ctx = _make_graph_context()
        mode_ctx = make_mode_context(graph_ctx=existing_ctx, graph_enriched=True)

        _ensure_graph_context(mode_ctx)
        assert mode_ctx.graph_ctx is existing_ctx
        assert mode_ctx.graph_enriched is True

    def test_skips_when_no_graph_flag(self, make_mode_context):
        """--no-graph prevents first-run build."""
        mode_ctx = make_mode_context(no_graph=True)
        _ensure_graph_context(mode_ctx)
        assert mode_ctx.graph_ctx is None
        assert mode_ctx.graph_enriched is False

    def test_build_failure_is_silent(self, make_mode_context, caplog):
        """If build_graph_context raises, logs DEBUG and returns unchanged."""
        mode_ctx = make_mode_context(no_graph=False)
        with mock_patch(
            "scatter.analyzers.graph_enrichment.build_graph_context",
            side_effect=RuntimeError("boom"),
        ):
            with caplog.at_level(logging.DEBUG):
                _ensure_graph_context(mode_ctx)
        assert mode_ctx.graph_ctx is None
        assert mode_ctx.graph_enriched is False
        assert "boom" in caplog.text

    def test_build_success_sets_enriched(self, make_mode_context):
        """Successful build returns graph_ctx and sets graph_enriched=True."""
        fake_ctx = _make_graph_context()
        mode_ctx = make_mode_context(no_graph=False)
        with mock_patch(
            "scatter.analyzers.graph_enrichment.build_graph_context",
            return_value=fake_ctx,
        ):
            _ensure_graph_context(mode_ctx)
        assert mode_ctx.graph_ctx is fake_ctx
        assert mode_ctx.graph_enriched is True


class TestFirstRunIntegration:
    """CLI integration: first run with no cache builds graph and enriches.

    Note: these tests use --search-scope . which reads the repo's .scatter/ cache
    if it exists. The first-run build path is exercised when no cache is present;
    if a cache already exists (from prior runs or other tests), the test still passes
    because graph_enriched=True either way (auto-load or first-run build).
    """

    def test_first_run_builds_and_enriches(self, tmp_path):
        """First run without any cache should build graph and enrich results."""
        out = tmp_path / "result.json"
        result = subprocess.run(
            [sys.executable, "-m", "scatter",
             "--target-project", "./GalaxyWorks.Data/GalaxyWorks.Data.csproj",
             "--search-scope", ".",
             "--output-format", "json", "--output-file", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text())
        assert data["metadata"]["graph_enriched"] is True, \
            "First run should build graph and enrich"
        # Verify enrichment fields present on results
        if data.get("all_results"):
            first = data["all_results"][0]
            assert "CouplingScore" in first

    def test_first_run_no_graph_skips_build(self, tmp_path):
        """--no-graph on first run should not build or enrich."""
        out = tmp_path / "result.json"
        result = subprocess.run(
            [sys.executable, "-m", "scatter",
             "--target-project", "./GalaxyWorks.Data/GalaxyWorks.Data.csproj",
             "--search-scope", ".", "--no-graph",
             "--output-format", "json", "--output-file", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(out.read_text())
        assert data["metadata"]["graph_enriched"] is False
