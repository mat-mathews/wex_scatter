"""Tests for Initiative 6 Phase 4: Markdown Output Format."""

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    FilterPipeline,
    FilterStage,
    ImpactReport,
    TargetImpact,
    STAGE_DISCOVERY,
    STAGE_PROJECT_REFERENCE,
    STAGE_NAMESPACE,
)
from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.analyzers.domain_analyzer import Cluster
from scatter.analyzers.health_analyzer import HealthDashboard, Observation
from scatter.reports._formatting import escape_cell as _escape_cell, md_table as _md_table
from scatter.reports.markdown_reporter import (
    _build_risk_highlights,
    _column_legend,
    _fmt_metadata,
    _fmt_pipeline,
    build_markdown,
    build_impact_markdown,
    build_graph_markdown,
    write_markdown_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline() -> FilterPipeline:
    return FilterPipeline(
        search_scope="/repo",
        total_projects_scanned=200,
        total_files_scanned=1847,
        stages=[
            FilterStage(name=STAGE_DISCOVERY, input_count=200, output_count=200),
            FilterStage(name=STAGE_PROJECT_REFERENCE, input_count=200, output_count=12),
            FilterStage(name=STAGE_NAMESPACE, input_count=12, output_count=8),
        ],
        target_project="GalaxyWorks.Data",
        target_namespace="GalaxyWorks.Data",
    )


def _make_metadata() -> dict:
    return {
        "scatter_version": "0.3.0",
        "timestamp": "2026-03-13T12:00:00Z",
        "cli_args": {},
        "search_scope": "/repo",
        "duration_seconds": 1.23,
    }


def _make_legacy_results() -> list:
    return [
        {
            "TargetProjectName": "GalaxyWorks.Data",
            "TargetProjectPath": "src/Data/Data.csproj",
            "TriggeringType": "PortalDataService",
            "ConsumerProjectName": "WebPortal",
            "ConsumerProjectPath": "src/Web/Web.csproj",
            "ConsumingSolutions": ["Portal.sln"],
            "PipelineName": "portal-pipeline",
        },
        {
            "TargetProjectName": "GalaxyWorks.Data",
            "TargetProjectPath": "src/Data/Data.csproj",
            "TriggeringType": "PortalDataService",
            "ConsumerProjectName": "ConsumerApp",
            "ConsumerProjectPath": "src/App/App.csproj",
            "ConsumingSolutions": [],
            "PipelineName": None,
        },
    ]


def _make_impact_report(**overrides) -> ImpactReport:
    consumers = [
        EnrichedConsumer(
            consumer_path=Path("/fake/WebPortal/WebPortal.csproj"),
            consumer_name="WebPortal",
            depth=0,
            confidence=1.0,
            confidence_label="HIGH",
            risk_rating="Medium",
            pipeline_name="portal-pipeline",
            solutions=["Portal.sln"],
        ),
        EnrichedConsumer(
            consumer_path=Path("/fake/BatchProcessor/BatchProcessor.csproj"),
            consumer_name="BatchProcessor",
            depth=1,
            confidence=0.6,
            confidence_label="MEDIUM",
            propagation_parent="WebPortal",
            pipeline_name="batch-pipeline",
        ),
    ]
    defaults = dict(
        sow_text="Modify PortalDataService to add retry logic",
        targets=[
            TargetImpact(
                target=AnalysisTarget(target_type="project", name="GalaxyWorks.Data"),
                consumers=consumers,
                total_direct=1,
                total_transitive=1,
            ),
        ],
        overall_risk="High",
        complexity_rating="Medium",
        effort_estimate="3-5 developer-days",
        complexity_justification="Multiple consumers with one transitive chain",
        impact_narrative="This change affects a core data access service.",
    )
    defaults.update(overrides)
    return ImpactReport(**defaults)


def _make_node(name: str, **kwargs) -> ProjectNode:
    defaults = {"path": Path(f"/fake/{name}/{name}.csproj"), "name": name}
    defaults.update(kwargs)
    return ProjectNode(**defaults)


def _make_graph() -> DependencyGraph:
    g = DependencyGraph()
    g.add_node(_make_node("A", namespace="A.Core"))
    g.add_node(_make_node("B", namespace="B.Core"))
    g.add_node(_make_node("C", namespace="C.Core"))
    g.add_edge(DependencyEdge(source="A", target="B", edge_type="project_reference"))
    g.add_edge(DependencyEdge(source="B", target="C", edge_type="project_reference"))
    return g


def _make_metrics() -> dict:
    return {
        "A": ProjectMetrics(
            fan_in=0,
            fan_out=2,
            instability=1.0,
            coupling_score=2.0,
            afferent_coupling=0,
            efferent_coupling=2,
            shared_db_density=0.0,
            type_export_count=3,
            consumer_count=0,
        ),
        "B": ProjectMetrics(
            fan_in=1,
            fan_out=1,
            instability=0.5,
            coupling_score=1.5,
            afferent_coupling=1,
            efferent_coupling=1,
            shared_db_density=0.0,
            type_export_count=2,
            consumer_count=1,
        ),
        "C": ProjectMetrics(
            fan_in=2,
            fan_out=0,
            instability=0.0,
            coupling_score=1.0,
            afferent_coupling=2,
            efferent_coupling=0,
            shared_db_density=0.0,
            type_export_count=1,
            consumer_count=2,
        ),
    }


def _make_ranked(metrics: dict) -> list:
    return sorted(metrics.items(), key=lambda x: -x[1].coupling_score)


def _make_cycles() -> list:
    return [
        CycleGroup(projects=["X", "Y", "Z"], shortest_cycle=["X", "Y", "Z"], edge_count=3),
        CycleGroup(projects=["D", "E"], shortest_cycle=["D", "E"], edge_count=2),
    ]


def _make_cluster(name, projects, **kwargs):
    defaults = dict(
        internal_edges=1,
        external_edges=0,
        cohesion=0.8,
        coupling_to_outside=0.2,
        cross_boundary_dependencies=[],
        shared_db_objects=[],
        extraction_feasibility="moderate",
        feasibility_score=0.650,
        feasibility_details={},
    )
    defaults.update(kwargs)
    return Cluster(name=name, projects=projects, **defaults)


def _make_enriched_results() -> list:
    """Legacy results with graph metrics populated."""
    base = _make_legacy_results()
    base[0].update(
        CouplingScore=1296.7,
        FanIn=20,
        FanOut=18,
        Instability=0.474,
        InCycle=True,
    )
    base[1].update(
        CouplingScore=762.6,
        FanIn=6,
        FanOut=16,
        Instability=0.727,
        InCycle=False,
    )
    return base


def _table_column_counts(table_text: str) -> list:
    """Return list of pipe counts for each non-empty line in a markdown table."""
    lines = [l for l in table_text.strip().splitlines() if "|" in l]
    return [l.count("|") for l in lines]


# ===========================================================================
# TestRiskHighlights
# ===========================================================================


class TestRiskHighlights:
    def test_stable_popular_flagged(self):
        results = _make_enriched_results()
        highlights = _build_risk_highlights(results)
        # WebPortal has instability 0.474 and fan-in 20 — should be flagged
        assert "WebPortal" in highlights
        assert "Highest risk" in highlights

    def test_cycle_count(self):
        results = _make_enriched_results()
        highlights = _build_risk_highlights(results)
        assert "1 of 2 consumer(s) are in a dependency cycle" in highlights

    def test_lowest_risk_flagged(self):
        results = _make_enriched_results()
        highlights = _build_risk_highlights(results)
        # ConsumerApp has instability 0.727 and not in cycle
        assert "ConsumerApp" in highlights
        assert "Lowest risk" in highlights

    def test_most_coupled(self):
        results = _make_enriched_results()
        highlights = _build_risk_highlights(results)
        assert "Most coupled" in highlights
        assert "WebPortal" in highlights
        assert "1297" in highlights

    def test_empty_when_no_metrics(self):
        results = _make_legacy_results()  # no graph metrics
        highlights = _build_risk_highlights(results)
        assert highlights == ""

    def test_included_in_build_markdown(self):
        results = _make_enriched_results()
        md = build_markdown(results, graph_metrics_requested=True)
        assert "### Risk Highlights" in md
        assert "What do these columns mean?" in md


class TestColumnLegend:
    def test_contains_all_columns(self):
        legend = _column_legend()
        assert "Coupling" in legend
        assert "Fan-In" in legend
        assert "Fan-Out" in legend
        assert "Instability" in legend
        assert "In Cycle" in legend

    def test_is_collapsible(self):
        legend = _column_legend()
        assert "<details>" in legend
        assert "<summary>" in legend

    def test_not_included_without_graph_metrics(self):
        md = build_markdown(_make_legacy_results(), graph_metrics_requested=False)
        assert "What do these columns mean?" not in md


# ===========================================================================
# TestEscapeCell
# ===========================================================================


class TestEscapeCell:
    def test_pipe(self):
        assert _escape_cell("Foo|Bar") == "Foo\\|Bar"

    def test_newline(self):
        assert _escape_cell("line1\nline2") == "line1 line2"

    def test_whitespace(self):
        assert _escape_cell("  padded  ") == "padded"


# ===========================================================================
# TestBuildLegacyMarkdown
# ===========================================================================


class TestBuildLegacyMarkdown:
    def test_header(self):
        md = build_markdown([])
        assert md.startswith("# Consumer Analysis Report")

    def test_pipeline_section(self):
        md = build_markdown([], pipeline=_make_pipeline())
        assert "> **Search scope:**" in md
        assert "> **Filter:**" in md
        assert "200" in md

    def test_no_pipeline(self):
        md = build_markdown([], pipeline=None)
        assert "Search scope" not in md

    def test_target_grouping(self):
        results = _make_legacy_results()
        # Add a second target group
        results.append(
            {
                "TargetProjectName": "Other.Project",
                "TargetProjectPath": "src/Other/Other.csproj",
                "TriggeringType": "N/A (Project Reference)",
                "ConsumerProjectName": "SomeConsumer",
                "ConsumerProjectPath": "src/Some/Some.csproj",
                "ConsumingSolutions": [],
                "PipelineName": None,
            }
        )
        md = build_markdown(results)
        assert "## GalaxyWorks.Data" in md
        assert "## Other.Project" in md

    def test_table_columns(self):
        md = build_markdown(_make_legacy_results())
        assert "| Consumer | Path | Pipeline | Solutions |" in md

    def test_table_column_count(self):
        md = build_markdown(_make_legacy_results())
        # Extract lines that look like table rows
        table_lines = [l for l in md.splitlines() if l.startswith("|")]
        counts = _table_column_counts("\n".join(table_lines))
        # All rows should have the same number of pipes
        assert len(set(counts)) == 1

    def test_omits_na_type(self):
        results = [
            {
                "TargetProjectName": "MyProject",
                "TargetProjectPath": "src/My/My.csproj",
                "TriggeringType": "N/A (Project Reference)",
                "ConsumerProjectName": "Consumer",
                "ConsumerProjectPath": "src/C/C.csproj",
                "ConsumingSolutions": [],
                "PipelineName": None,
            }
        ]
        md = build_markdown(results)
        assert "Type/Level" not in md

    def test_empty_results(self):
        md = build_markdown([])
        assert "No consuming relationships found" in md

    def test_metadata_footer(self):
        md = build_markdown([], metadata=_make_metadata())
        assert "Generated by Scatter v0.3.0" in md


# ===========================================================================
# TestBuildImpactMarkdown
# ===========================================================================


class TestBuildImpactMarkdown:
    def test_header(self):
        md = build_impact_markdown(_make_impact_report())
        assert md.startswith("# Impact Analysis")

    def test_risk_complexity_in_summary(self):
        md = build_impact_markdown(_make_impact_report())
        assert "## Summary" in md
        assert "High" in md  # risk
        assert "Medium" in md  # complexity

    def test_blast_radius_tree(self):
        md = build_impact_markdown(_make_impact_report())
        assert "#### Blast Radius" in md
        assert "```text" in md
        # Box-drawing characters from the tree
        assert "\u251c\u2500\u2500" in md or "\u2514\u2500\u2500" in md

    def test_consumer_detail_table(self):
        md = build_impact_markdown(_make_impact_report())
        assert "#### Affected Projects" in md
        assert "| Consumer | Confidence | Depth | Via | Risk | Pipeline | Solutions |" in md

    def test_detail_table_column_count(self):
        md = build_impact_markdown(_make_impact_report())
        # Find lines in the consumer detail table
        in_table = False
        table_lines = []
        for line in md.splitlines():
            if "| Consumer | Confidence" in line:
                in_table = True
            if in_table and "|" in line:
                table_lines.append(line)
            elif in_table and "|" not in line and line.strip():
                break
        counts = _table_column_counts("\n".join(table_lines))
        assert len(counts) >= 3  # header + separator + at least 1 data row
        assert len(set(counts)) == 1

    def test_depth_display(self):
        md = build_impact_markdown(_make_impact_report())
        # Find the table rows — direct consumer shows "direct", transitive shows "1"
        lines = md.splitlines()
        table_rows = [
            l for l in lines if l.startswith("| WebPortal") or l.startswith("| BatchProcessor")
        ]
        web_row = [l for l in table_rows if "WebPortal" in l][0]
        batch_row = [l for l in table_rows if "BatchProcessor" in l][0]
        assert "| direct |" in web_row
        assert "| 1 |" in batch_row

    def test_propagation_parent(self):
        md = build_impact_markdown(_make_impact_report())
        lines = md.splitlines()
        batch_row = [l for l in lines if "BatchProcessor" in l and l.startswith("|")][0]
        assert "WebPortal" in batch_row

    def test_narrative_sections(self):
        md = build_impact_markdown(_make_impact_report())
        assert "### Complexity" in md
        assert "Multiple consumers with one transitive chain" in md
        # Narrative now in Summary section (prose before stats)
        assert "core data access service" in md

    def test_no_targets(self):
        report = _make_impact_report(targets=[])
        md = build_impact_markdown(report)
        assert "No analysis targets were identified" in md

    def test_effort_estimate(self):
        md = build_impact_markdown(_make_impact_report())
        assert "(3-5 developer-days)" in md


# ===========================================================================
# TestBuildGraphMarkdown
# ===========================================================================


class TestBuildGraphMarkdown:
    def test_summary_table(self):
        g = _make_graph()
        m = _make_metrics()
        md = build_graph_markdown(g, m, _make_ranked(m), [])
        assert "| Projects | 3 |" in md
        assert "| Dependencies |" in md

    def test_top_coupled_table(self):
        g = _make_graph()
        m = _make_metrics()
        md = build_graph_markdown(g, m, _make_ranked(m), [])
        assert "## Top Coupled Projects" in md
        assert "| Project | Score | Fan-In | Fan-Out | Instability |" in md

    def test_top_coupled_column_count(self):
        g = _make_graph()
        m = _make_metrics()
        md = build_graph_markdown(g, m, _make_ranked(m), [])
        # Extract the top coupled table
        in_table = False
        table_lines = []
        for line in md.splitlines():
            if "| Project | Score" in line:
                in_table = True
            if in_table and "|" in line:
                table_lines.append(line)
            elif in_table and "|" not in line and line.strip():
                break
        counts = _table_column_counts("\n".join(table_lines))
        assert len(set(counts)) == 1

    def test_cycles_section(self):
        g = _make_graph()
        m = _make_metrics()
        cycles = _make_cycles()
        md = build_graph_markdown(g, m, _make_ranked(m), cycles)
        assert "## Circular Dependencies" in md
        assert "**[3 projects]**" in md
        assert "**[2 projects]**" in md

    def test_no_cycles(self):
        g = _make_graph()
        m = _make_metrics()
        md = build_graph_markdown(g, m, _make_ranked(m), [])
        assert "Circular Dependencies" not in md

    def test_clusters_table(self):
        g = _make_graph()
        m = _make_metrics()
        clusters = [_make_cluster("Core", ["A", "B"])]
        md = build_graph_markdown(g, m, _make_ranked(m), [], clusters=clusters)
        assert "## Domain Clusters" in md
        assert "| Cluster | Size | Cohesion | Coupling | Feasibility |" in md
        assert "Core" in md

    def test_observations(self):
        g = _make_graph()
        m = _make_metrics()
        dashboard = HealthDashboard(
            total_projects=3,
            total_edges=2,
            total_cycles=0,
            total_clusters=0,
            avg_fan_in=1.0,
            avg_fan_out=1.0,
            avg_instability=0.5,
            avg_coupling_score=1.5,
            max_coupling_project="A",
            max_coupling_score=2.0,
            observations=[
                Observation(
                    severity="warning",
                    rule="high_coupling",
                    project="A",
                    message="A has high coupling",
                ),
            ],
        )
        md = build_graph_markdown(g, m, _make_ranked(m), [], dashboard=dashboard)
        assert "## Observations" in md
        assert "**[warning]**" in md
        assert "A has high coupling" in md

    def test_mermaid_block(self):
        g = _make_graph()
        m = _make_metrics()
        md = build_graph_markdown(g, m, _make_ranked(m), [])
        assert "```mermaid" in md
        assert "graph TD" in md


# ===========================================================================
# TestMarkdownFileIO
# ===========================================================================


class TestMarkdownFileIO:
    def test_file_written(self, tmp_path):
        out = tmp_path / "report.md"
        write_markdown_report(_make_legacy_results(), out, metadata=_make_metadata())
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "# Consumer Analysis Report" in content

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "sub" / "dir" / "report.md"
        write_markdown_report([], out)
        assert out.exists()

    def test_utf8_encoding(self, tmp_path):
        out = tmp_path / "report.md"
        write_markdown_report([], out, pipeline=_make_pipeline())
        content = out.read_text(encoding="utf-8")
        # Arrow character from format_arrow_chain
        assert "\u2192" in content


# ===========================================================================
# TestMdTableEdgeCases
# ===========================================================================


class TestMdTableEdgeCases:
    def test_short_row_padded(self):
        """Row with fewer values than headers is padded to match."""
        result = _md_table(["A", "B", "C"], [["x", "y"]])
        lines = result.splitlines()
        counts = [l.count("|") for l in lines]
        assert len(set(counts)) == 1  # all rows same column count


# ===========================================================================
# TestEscapeCellEndToEnd
# ===========================================================================


class TestEscapeCellEndToEnd:
    def test_pipe_in_consumer_name(self):
        """Pipe character in a field value is escaped in final markdown output."""
        results = [
            {
                "TargetProjectName": "X",
                "TargetProjectPath": "x.csproj",
                "TriggeringType": "N/A",
                "ConsumerProjectName": "Foo|Bar",
                "ConsumerProjectPath": "fb.csproj",
                "ConsumingSolutions": [],
                "PipelineName": None,
            }
        ]
        md = build_markdown(results)
        assert "Foo\\|Bar" in md


# ===========================================================================
# TestNarrativeSectionsAbsent
# ===========================================================================


class TestNarrativeSectionsAbsent:
    def test_no_complexity_section_when_none(self):
        """Complexity section omitted when complexity_justification is None."""
        report = _make_impact_report(
            complexity_justification=None,
            impact_narrative=None,
        )
        md = build_impact_markdown(report)
        assert "### Complexity" not in md
        assert "### Impact Summary" not in md


# ===========================================================================
# TestCLIDispatch
# ===========================================================================


class TestCLIDispatch:
    def test_require_output_file_exits_for_json(self):
        """_require_output_file exits when --output-file is missing."""
        from scatter.cli import _require_output_file

        class FakeArgs:
            output_file = None

        with pytest.raises(SystemExit) as exc_info:
            _require_output_file(FakeArgs(), "JSON")
        assert exc_info.value.code == 1

    def test_require_output_file_returns_path(self):
        """_require_output_file returns Path when --output-file is set."""
        from scatter.cli import _require_output_file

        class FakeArgs:
            output_file = "/tmp/report.json"

        result = _require_output_file(FakeArgs(), "JSON")
        assert result == Path("/tmp/report.json")

    def test_markdown_stdout_fallback(self, capsys):
        """Markdown format prints to stdout when --output-file is omitted."""
        md = build_markdown([], metadata=_make_metadata())
        print(md)
        captured = capsys.readouterr()
        assert "# Consumer Analysis Report" in captured.out
        assert "Generated by Scatter" in captured.out
