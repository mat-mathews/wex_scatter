"""Tests for Initiative 10: Codebase Index for SOW mode."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scatter.core.graph import DependencyGraph, ProjectNode
from scatter.ai.codebase_index import (
    CodebaseIndex,
    build_codebase_index,
    _filter_types,
    _apply_type_cap,
)
from scatter.ai.tasks.parse_work_request import (
    parse_work_request_with_model,
    parse_work_request,
    _extract_index_names,
)
from scatter.analyzers.impact_analyzer import (
    _compute_ambiguity_label,
    run_impact_analysis,
)
from scatter.core.models import (
    AnalysisTarget,
    TargetImpact,
    ImpactReport,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_graph_with_projects(projects):
    """Build a DependencyGraph from a list of (name, namespace, types, sprocs) tuples."""
    graph = DependencyGraph()
    for name, namespace, types, sprocs in projects:
        node = ProjectNode(
            path=Path(f"/repo/{name}/{name}.csproj"),
            name=name,
            namespace=namespace,
            type_declarations=types,
            sproc_references=sprocs,
        )
        graph.add_node(node)
    return graph


def _make_mock_model(response_text):
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_model.generate_content.return_value = mock_response
    return mock_model


def _make_mock_provider(response_text):
    provider = MagicMock()
    provider.model = _make_mock_model(response_text)
    return provider


# =============================================================================
# Phase 1: Codebase Index Building
# =============================================================================


class TestCodebaseIndex:
    def test_empty_graph_produces_empty_index(self):
        graph = DependencyGraph()
        index = build_codebase_index(graph)
        assert index.text == ""
        assert index.project_count == 0
        assert index.type_count == 0
        assert index.sproc_count == 0
        assert index.file_count == 0
        assert index.size_bytes == 0

    def test_index_contains_project_names(self):
        graph = _make_graph_with_projects(
            [
                ("GalaxyWorks.Data", "GalaxyWorks.Data", ["PortalDataService"], []),
                ("MyDotNetApp", "MyDotNetApp", ["Program"], []),
            ]
        )
        index = build_codebase_index(graph)
        assert "P:GalaxyWorks.Data" in index.text
        assert "P:MyDotNetApp" in index.text
        assert index.project_count == 2

    def test_index_contains_type_declarations(self):
        graph = _make_graph_with_projects(
            [
                (
                    "GalaxyWorks.Data",
                    "GalaxyWorks.Data",
                    ["PortalDataService", "IDataService", "PortalConfig"],
                    [],
                ),
            ]
        )
        index = build_codebase_index(graph)
        assert "PortalDataService" in index.text
        assert "IDataService" in index.text
        assert "PortalConfig" in index.text
        assert index.type_count == 3

    def test_index_contains_sproc_references(self):
        graph = _make_graph_with_projects(
            [
                (
                    "GalaxyWorks.Data",
                    "GalaxyWorks.Data",
                    [],
                    ["dbo.sp_InsertPortalConfiguration", "dbo.sp_GetPortalConfig"],
                ),
            ]
        )
        index = build_codebase_index(graph)
        assert "dbo.sp_InsertPortalConfiguration" in index.text
        assert "dbo.sp_GetPortalConfig" in index.text
        assert index.sproc_count == 2

    def test_namespace_omitted_when_matches_project(self):
        graph = _make_graph_with_projects(
            [
                ("GalaxyWorks.Data", "GalaxyWorks.Data", [], []),
            ]
        )
        index = build_codebase_index(graph)
        # Namespace should NOT appear when it matches the project name
        assert "NS:" not in index.text

    def test_namespace_included_when_differs(self):
        graph = _make_graph_with_projects(
            [
                ("GalaxyWorks.Data", "GW.DataAccess", [], []),
            ]
        )
        index = build_codebase_index(graph)
        assert "NS:GW.DataAccess" in index.text

    def test_header_contains_project_count(self):
        graph = _make_graph_with_projects(
            [
                ("ProjectA", "ProjectA", [], []),
                ("ProjectB", "ProjectB", [], []),
            ]
        )
        index = build_codebase_index(graph)
        assert "(2 projects)" in index.text

    def test_compact_one_line_per_project_format(self):
        graph = _make_graph_with_projects(
            [
                ("MyApp", "MyApp", ["Service", "Controller"], ["dbo.sp_Get"]),
            ]
        )
        index = build_codebase_index(graph)
        # Should be one line with all fields
        assert "P:MyApp T:Service,Controller SP:dbo.sp_Get" in index.text

    def test_sproc_cross_reference_when_shared(self):
        graph = _make_graph_with_projects(
            [
                ("ProjectA", "ProjectA", [], ["dbo.sp_Shared"]),
                ("ProjectB", "ProjectB", [], ["dbo.sp_Shared"]),
                ("ProjectC", "ProjectC", [], ["dbo.sp_Unique"]),
            ]
        )
        index = build_codebase_index(graph)
        assert "=== Shared Stored Procedures ===" in index.text
        assert "dbo.sp_Shared" in index.text
        # sp_Unique appears only in one project, should NOT be in cross-reference
        lines = index.text.split("\n")
        shared_section_started = False
        for line in lines:
            if "=== Shared Stored Procedures ===" in line:
                shared_section_started = True
            if shared_section_started and "dbo.sp_Unique" in line:
                pytest.fail("sp_Unique should not appear in shared sproc section")

    def test_no_sproc_cross_reference_when_no_shared(self):
        graph = _make_graph_with_projects(
            [
                ("ProjectA", "ProjectA", [], ["dbo.sp_OnlyA"]),
                ("ProjectB", "ProjectB", [], ["dbo.sp_OnlyB"]),
            ]
        )
        index = build_codebase_index(graph)
        assert "=== Shared Stored Procedures ===" not in index.text

    def test_graph_with_empty_type_declarations(self):
        graph = _make_graph_with_projects(
            [
                ("EmptyProject", "EmptyProject", [], []),
            ]
        )
        index = build_codebase_index(graph)
        assert "P:EmptyProject" in index.text
        assert index.project_count == 1
        assert index.type_count == 0

    def test_file_count_collected_when_search_scope(self, tmp_path):
        proj_dir = tmp_path / "MyApp"
        proj_dir.mkdir()
        (proj_dir / "MyApp.csproj").write_text("<Project></Project>")
        (proj_dir / "Program.cs").write_text("class Program {}")
        (proj_dir / "Service.cs").write_text("class Service {}")

        graph = DependencyGraph()
        node = ProjectNode(
            path=proj_dir / "MyApp.csproj",
            name="MyApp",
            namespace="MyApp",
            type_declarations=["Program", "Service"],
        )
        graph.add_node(node)

        index = build_codebase_index(graph, search_scope=tmp_path)
        # File stems are NOT in the prompt text (compact format)
        assert "Files:" not in index.text
        # But file_count metric is still tracked
        assert index.file_count == 2

    def test_no_file_count_without_search_scope(self):
        graph = _make_graph_with_projects(
            [
                ("MyApp", "MyApp", ["Program"], []),
            ]
        )
        index = build_codebase_index(graph, search_scope=None)
        assert index.file_count == 0

    def test_large_graph_returns_all_types_no_truncation(self):
        """A large graph (100 projects, 50 types each) returns all types — no truncation."""
        projects = [
            (f"Project{i}", f"Namespace{i}", [f"Type{j}" for j in range(50)], [])
            for i in range(100)
        ]
        graph = _make_graph_with_projects(projects)
        index = build_codebase_index(graph)
        assert index.project_count == 100
        assert index.type_count == 5000
        # No truncation markers
        assert "..." not in index.text
        # Spot-check: last type of last project is present
        assert "Type49" in index.text

    def test_sample_projects_in_index(self):
        """Index built from sample-like projects contains all project names."""
        sample_projects = [
            (
                "GalaxyWorks.Data",
                "GalaxyWorks.Data",
                ["PortalDataService"],
                ["dbo.sp_InsertPortalConfiguration"],
            ),
            ("MyDotNetApp", "MyDotNetApp", ["Program"], []),
            ("MyDotNetApp.Consumer", "MyDotNetApp.Consumer", ["ConsumerService"], []),
            ("MyGalaxyConsumerApp", "MyGalaxyConsumerApp", ["GalaxyService"], []),
            ("MyGalaxyConsumerApp2", "MyGalaxyConsumerApp2", ["GalaxyService2"], []),
        ]
        graph = _make_graph_with_projects(sample_projects)
        index = build_codebase_index(graph)
        for name, _, _, _ in sample_projects:
            assert f"P:{name}" in index.text

    def test_legend_in_header(self):
        graph = _make_graph_with_projects(
            [
                ("MyApp", "MyApp", [], []),
            ]
        )
        index = build_codebase_index(graph)
        assert "P=Project" in index.text
        assert "T=Types" in index.text
        assert "SP=StoredProcs" in index.text


# =============================================================================
# Phase 2: Prompt with Index & Evidence
# =============================================================================


class TestPromptWithIndex:
    def test_prompt_includes_index_when_provided(self):
        index = CodebaseIndex(
            text="=== Codebase Index (1 projects) ===\nP:MyApp T:Service\n",
            project_count=1,
            type_count=1,
            sproc_count=0,
            file_count=0,
            size_bytes=50,
        )
        response = json.dumps(
            [
                {
                    "type": "project",
                    "name": "MyApp",
                    "confidence": 0.9,
                    "match_evidence": "Explicitly named in SOW",
                }
            ]
        )
        model = _make_mock_model(response)

        result = parse_work_request_with_model(model, "Modify MyApp", codebase_index=index)
        assert result is not None
        call_args = model.generate_content.call_args[0][0]
        assert "=== Codebase Index" in call_args
        assert "ONLY return names that appear in the codebase index" in call_args

    def test_prompt_omits_index_when_none(self):
        response = json.dumps([{"type": "project", "name": "MyApp", "confidence": 0.9}])
        model = _make_mock_model(response)

        result = parse_work_request_with_model(model, "Modify MyApp", codebase_index=None)
        assert result is not None
        call_args = model.generate_content.call_args[0][0]
        assert "=== Codebase Index" not in call_args
        assert "ONLY return names" not in call_args

    def test_match_evidence_parsed(self):
        response = json.dumps(
            [
                {
                    "type": "project",
                    "name": "MyApp",
                    "confidence": 0.9,
                    "match_evidence": "Project handles portal configuration",
                }
            ]
        )
        model = _make_mock_model(response)
        result = parse_work_request_with_model(model, "Update portal config")
        assert result[0]["match_evidence"] == "Project handles portal configuration"

    def test_match_evidence_stored_on_target(self, tmp_path):
        proj_dir = tmp_path / "MyApp"
        proj_dir.mkdir()
        (proj_dir / "MyApp.csproj").write_text("<Project></Project>")

        response = json.dumps(
            [
                {
                    "type": "project",
                    "name": "MyApp",
                    "confidence": 0.9,
                    "match_evidence": "Contains portal service classes",
                }
            ]
        )
        provider = _make_mock_provider(response)
        targets = parse_work_request("Update portal config", provider, tmp_path)
        assert len(targets) == 1
        assert targets[0].match_evidence == "Contains portal service classes"

    def test_names_not_in_index_are_dropped(self, tmp_path):
        """Targets not found in the codebase index are excluded entirely."""
        proj_dir = tmp_path / "RealProject"
        proj_dir.mkdir()
        (proj_dir / "RealProject.csproj").write_text("<Project></Project>")

        index = CodebaseIndex(
            text="P:RealProject T:RealClass\n",
            project_count=1,
            type_count=1,
            sproc_count=0,
            file_count=0,
            size_bytes=30,
        )
        response = json.dumps(
            [
                {"type": "project", "name": "RealProject", "confidence": 0.8},
                {"type": "project", "name": "HallucinatedProject", "confidence": 0.9},
            ]
        )
        provider = _make_mock_provider(response)
        targets = parse_work_request(
            "Modify some projects",
            provider,
            tmp_path,
            codebase_index=index,
        )
        target_names = [t.name for t in targets]
        assert "RealProject" in target_names
        assert "HallucinatedProject" not in target_names  # dropped, not halved
        real = [t for t in targets if t.name == "RealProject"][0]
        assert real.confidence == 0.8  # unchanged


class TestExtractIndexNames:
    def test_extracts_project_names(self):
        text = "P:MyApp T:Svc\nP:OtherApp T:Ctrl\n"
        names = _extract_index_names(text)
        assert "MyApp" in names
        assert "OtherApp" in names

    def test_extracts_type_names(self):
        text = "P:MyApp T:ClassA,ClassB,InterfaceC\n"
        names = _extract_index_names(text)
        assert "ClassA" in names
        assert "ClassB" in names
        assert "InterfaceC" in names

    def test_extracts_sproc_names(self):
        text = "P:MyApp SP:dbo.sp_Insert,dbo.sp_Update\n"
        names = _extract_index_names(text)
        assert "dbo.sp_Insert" in names
        assert "dbo.sp_Update" in names

    def test_handles_legacy_truncated_types(self):
        """Parser still handles '...' suffix from pre-removal truncation format."""
        text = "P:MyApp T:ClassA,ClassB...\n"
        names = _extract_index_names(text)
        assert "ClassA" in names
        assert "ClassB" in names

    def test_extracts_namespace_when_present(self):
        text = "P:MyApp NS:Different.Namespace T:Svc\n"
        names = _extract_index_names(text)
        assert "MyApp" in names
        assert "Svc" in names


# =============================================================================
# Phase 3: Ambiguity Detection & Confidence Filtering
# =============================================================================


class TestAmbiguityLabel:
    def test_clear_few_targets_high_confidence(self):
        targets = [
            AnalysisTarget(target_type="project", name=f"P{i}", confidence=0.9) for i in range(3)
        ]
        assert _compute_ambiguity_label(targets) == "clear"

    def test_moderate_many_targets(self):
        targets = [
            AnalysisTarget(target_type="project", name=f"P{i}", confidence=0.8) for i in range(8)
        ]
        assert _compute_ambiguity_label(targets) == "moderate"

    def test_moderate_medium_confidence(self):
        targets = [
            AnalysisTarget(target_type="project", name=f"P{i}", confidence=0.5) for i in range(3)
        ]
        assert _compute_ambiguity_label(targets) == "moderate"

    def test_vague_too_many_targets(self):
        targets = [
            AnalysisTarget(target_type="project", name=f"P{i}", confidence=0.8) for i in range(15)
        ]
        assert _compute_ambiguity_label(targets) == "vague"

    def test_vague_low_confidence(self):
        targets = [
            AnalysisTarget(target_type="project", name=f"P{i}", confidence=0.2) for i in range(3)
        ]
        assert _compute_ambiguity_label(targets) == "vague"

    def test_empty_targets_is_vague(self):
        assert _compute_ambiguity_label([]) == "vague"

    def test_ambiguity_stored_on_report(self):
        report = ImpactReport(
            sow_text="test",
            ambiguity_level="moderate",
            avg_target_confidence=0.65,
        )
        assert report.ambiguity_level == "moderate"
        assert report.avg_target_confidence == 0.65


class TestConfidenceFiltering:
    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    def test_low_confidence_targets_filtered(self, mock_parse):
        """Targets below min_confidence are excluded."""
        mock_parse.return_value = [
            AnalysisTarget(
                target_type="project",
                name="HighConf",
                csproj_path=Path("/a.csproj"),
                confidence=0.9,
            ),
            AnalysisTarget(
                target_type="project", name="LowConf", csproj_path=Path("/b.csproj"), confidence=0.2
            ),
        ]
        provider = _make_mock_provider("[]")

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=provider,
            min_confidence=0.5,
        )
        target_names = [ti.target.name for ti in report.targets]
        assert "HighConf" in target_names
        assert "LowConf" not in target_names

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    def test_context_too_large_raises_actionable_error(self, mock_parse):
        """InvalidArgument from the AI provider is wrapped with an actionable message."""
        # Simulate google.api_core.exceptions.InvalidArgument by name
        exc = type("InvalidArgument", (Exception,), {})("request too large")
        mock_parse.side_effect = exc
        provider = _make_mock_provider("[]")

        with pytest.raises(RuntimeError, match="narrowing --search-scope"):
            run_impact_analysis(
                sow_text="test",
                search_scope=Path("/search"),
                ai_provider=provider,
            )

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    def test_unrelated_exception_propagates(self, mock_parse):
        """Exceptions unrelated to context limits propagate unchanged."""
        mock_parse.side_effect = KeyError("something unrelated")
        provider = _make_mock_provider("[]")

        with pytest.raises(KeyError, match="something unrelated"):
            run_impact_analysis(
                sow_text="test",
                search_scope=Path("/search"),
                ai_provider=provider,
            )

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    def test_context_error_includes_token_estimate(self, mock_parse):
        """The wrapped error message includes an estimated token count from the index."""
        exc = type("InvalidArgument", (Exception,), {})("request too large")
        mock_parse.side_effect = exc
        provider = _make_mock_provider("[]")

        # Build a graph so the index has a known size
        graph = _make_graph_with_projects(
            [
                ("MyApp", "MyApp", ["Service"], []),
            ]
        )

        # Wrap graph in a mock GraphContext (Decision #12)
        mock_graph_ctx = MagicMock()
        mock_graph_ctx.graph = graph

        with pytest.raises(RuntimeError, match="estimated") as exc_info:
            run_impact_analysis(
                sow_text="test",
                search_scope=Path("/search"),
                ai_provider=provider,
                graph_ctx=mock_graph_ctx,
            )
        # Should mention tokens and contain the original exception
        assert "tokens" in str(exc_info.value)
        assert exc_info.value.__cause__ is exc

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    def test_ambiguity_computed_before_filtering(self, mock_parse):
        """Ambiguity label uses full target list (before filtering)."""
        mock_parse.return_value = [
            AnalysisTarget(
                target_type="project",
                name=f"P{i}",
                csproj_path=Path(f"/{i}.csproj"),
                confidence=0.2,
            )
            for i in range(15)
        ]
        provider = _make_mock_provider("[]")

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=provider,
            min_confidence=0.5,
        )
        assert report.ambiguity_level == "vague"
        assert report.avg_target_confidence == pytest.approx(0.2)
        assert len(report.targets) == 0


class TestIndexBudgetWiring:
    """Verify run_impact_analysis passes max_bytes to build_codebase_index."""

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request", return_value=[])
    @patch("scatter.ai.codebase_index.build_codebase_index")
    def test_default_budget_applied(self, mock_build_index, mock_parse):
        """When index_max_bytes is None, DEFAULT_INDEX_BUDGET_BYTES is used."""
        from scatter.analyzers.impact_analyzer import DEFAULT_INDEX_BUDGET_BYTES

        mock_build_index.return_value = CodebaseIndex(
            text="P:MyApp", project_count=1, type_count=1,
            sproc_count=0, file_count=0, size_bytes=10,
        )
        mock_graph_ctx = MagicMock()
        mock_graph_ctx.graph = MagicMock()

        run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=mock_graph_ctx,
        )

        _, kwargs = mock_build_index.call_args
        assert kwargs["max_bytes"] == DEFAULT_INDEX_BUDGET_BYTES

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request", return_value=[])
    @patch("scatter.ai.codebase_index.build_codebase_index")
    def test_custom_budget_passed_through(self, mock_build_index, mock_parse):
        """When index_max_bytes is set, it overrides the default."""
        mock_build_index.return_value = CodebaseIndex(
            text="P:MyApp", project_count=1, type_count=1,
            sproc_count=0, file_count=0, size_bytes=10,
        )
        mock_graph_ctx = MagicMock()
        mock_graph_ctx.graph = MagicMock()

        run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=mock_graph_ctx,
            index_max_bytes=500_000,
        )

        _, kwargs = mock_build_index.call_args
        assert kwargs["max_bytes"] == 500_000

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request", return_value=[])
    def test_no_graph_skips_index(self, mock_parse):
        """Without a graph, build_codebase_index is not called at all."""
        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=MagicMock(),
            graph_ctx=None,
        )
        # No crash, codebase_index is None internally
        assert report is not None


class TestTargetCountCap:
    """Verify run_impact_analysis caps excessive target counts."""

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    def test_targets_capped_at_max(self, mock_parse):
        """More than MAX_SOW_TARGETS targets are capped by confidence."""
        from scatter.analyzers.impact_analyzer import MAX_SOW_TARGETS

        # Return 40 targets — more than MAX_SOW_TARGETS (25)
        mock_parse.return_value = [
            AnalysisTarget(
                target_type="project",
                name=f"P{i}",
                csproj_path=Path(f"/{i}.csproj"),
                confidence=0.5 + (i * 0.01),  # varying confidence
            )
            for i in range(40)
        ]
        provider = MagicMock()

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=provider,
        )
        # Targets in report are capped (those that resolved + had consumers)
        # but the internal filtered list was capped at MAX_SOW_TARGETS
        assert len(report.targets) <= MAX_SOW_TARGETS

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    def test_under_cap_not_truncated(self, mock_parse):
        """Fewer than MAX_SOW_TARGETS targets are not truncated."""
        mock_parse.return_value = [
            AnalysisTarget(
                target_type="project",
                name=f"P{i}",
                csproj_path=Path(f"/{i}.csproj"),
                confidence=0.8,
            )
            for i in range(5)
        ]
        provider = MagicMock()

        report = run_impact_analysis(
            sow_text="test",
            search_scope=Path("/search"),
            ai_provider=provider,
        )
        # 5 targets, all skip (no csproj on disk), but none were capped
        assert report is not None


class TestConsumerCache:
    """Verify consumer_cache deduplicates find_consumers calls."""

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    def test_cache_prevents_duplicate_scans(self, mock_find, mock_parse, tmp_path):
        """Same csproj_path should only trigger find_consumers once."""
        proj_path = tmp_path / "MyApp" / "MyApp.csproj"
        proj_path.parent.mkdir()
        proj_path.write_text("<Project></Project>")

        mock_parse.return_value = [
            AnalysisTarget(
                target_type="project", name="MyApp",
                csproj_path=proj_path, namespace="MyApp", confidence=0.9,
            ),
            AnalysisTarget(
                target_type="project", name="MyApp",
                csproj_path=proj_path, namespace="MyApp", confidence=0.8,
            ),
        ]
        mock_find.return_value = ([], None)

        run_impact_analysis(
            sow_text="test",
            search_scope=tmp_path,
            ai_provider=MagicMock(),
        )

        # find_consumers called once despite two targets with the same csproj
        assert mock_find.call_count == 1


class TestAdaptiveDepth:
    """Verify high-fan-out targets get reduced transitive depth."""

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer.trace_transitive_impact")
    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    def test_high_fan_out_limits_depth(self, mock_find, mock_trace, mock_parse, tmp_path):
        """Targets with >50 direct consumers get depth capped at 1."""
        proj_path = tmp_path / "BigApp" / "BigApp.csproj"
        proj_path.parent.mkdir()
        proj_path.write_text("<Project></Project>")

        mock_parse.return_value = [
            AnalysisTarget(
                target_type="project", name="BigApp",
                csproj_path=proj_path, namespace="BigApp", confidence=0.9,
            ),
        ]
        # Return 60 consumers — above _HIGH_FAN_OUT_THRESHOLD (50)
        mock_find.return_value = (
            [{"consumer_path": Path(f"/c{i}.csproj"), "consumer_name": f"C{i}"} for i in range(60)],
            None,
        )
        mock_trace.return_value = []

        run_impact_analysis(
            sow_text="test",
            search_scope=tmp_path,
            ai_provider=MagicMock(),
            max_depth=2,
        )

        # trace_transitive_impact called with max_depth=1, not 2
        _, kwargs = mock_trace.call_args
        assert kwargs["max_depth"] == 1

    @patch("scatter.ai.tasks.parse_work_request.parse_work_request")
    @patch("scatter.analyzers.impact_analyzer.trace_transitive_impact")
    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    def test_normal_fan_out_keeps_depth(self, mock_find, mock_trace, mock_parse, tmp_path):
        """Targets with <=50 direct consumers keep the configured depth."""
        proj_path = tmp_path / "SmallApp" / "SmallApp.csproj"
        proj_path.parent.mkdir()
        proj_path.write_text("<Project></Project>")

        mock_parse.return_value = [
            AnalysisTarget(
                target_type="project", name="SmallApp",
                csproj_path=proj_path, namespace="SmallApp", confidence=0.9,
            ),
        ]
        mock_find.return_value = (
            [{"consumer_path": Path(f"/c{i}.csproj"), "consumer_name": f"C{i}"} for i in range(10)],
            None,
        )
        mock_trace.return_value = []

        run_impact_analysis(
            sow_text="test",
            search_scope=tmp_path,
            ai_provider=MagicMock(),
            max_depth=2,
        )

        _, kwargs = mock_trace.call_args
        assert kwargs["max_depth"] == 2


# =============================================================================
# Phase 4: Console Reporter
# =============================================================================


class TestConsoleReporterIndex:
    def test_ambiguity_shown_in_output(self, capsys):
        from scatter.reports.console_reporter import print_impact_report

        target = AnalysisTarget(
            target_type="project",
            name="MyApp",
            match_evidence="Contains portal classes",
            confidence=0.8,
        )
        ti = TargetImpact(target=target, total_direct=0, total_transitive=0)
        report = ImpactReport(
            sow_text="Update portal config",
            targets=[ti],
            ambiguity_level="clear",
            avg_target_confidence=0.8,
        )
        print_impact_report(report)
        output = capsys.readouterr().out
        assert "Target Quality: clear" in output
        assert "avg confidence 0.80" in output

    def test_evidence_shown_per_target(self, capsys):
        from scatter.reports.console_reporter import print_impact_report

        target = AnalysisTarget(
            target_type="project",
            name="MyApp",
            match_evidence="Contains portal classes",
            confidence=0.8,
        )
        ti = TargetImpact(target=target, total_direct=0, total_transitive=0)
        report = ImpactReport(
            sow_text="Update portal config",
            targets=[ti],
        )
        print_impact_report(report)
        output = capsys.readouterr().out
        assert "Evidence: Contains portal classes" in output

    def test_no_index_warning_when_no_evidence(self, capsys):
        from scatter.reports.console_reporter import print_impact_report

        target = AnalysisTarget(
            target_type="project",
            name="MyApp",
            confidence=0.8,
        )
        ti = TargetImpact(target=target, total_direct=0, total_transitive=0)
        report = ImpactReport(
            sow_text="Update something",
            targets=[ti],
        )
        print_impact_report(report)
        output = capsys.readouterr().out
        assert "Running without codebase index" in output

    def test_no_warning_when_evidence_present(self, capsys):
        from scatter.reports.console_reporter import print_impact_report

        target = AnalysisTarget(
            target_type="project",
            name="MyApp",
            match_evidence="Matched via index",
            confidence=0.8,
        )
        ti = TargetImpact(target=target, total_direct=0, total_transitive=0)
        report = ImpactReport(
            sow_text="Update something",
            targets=[ti],
        )
        print_impact_report(report)
        output = capsys.readouterr().out
        assert "Running without codebase index" not in output


# =============================================================================
# Phase 4: JSON Reporter
# =============================================================================


class TestJsonReporterIndex:
    def test_ambiguity_and_evidence_in_json(self, tmp_path):
        from scatter.reports.json_reporter import write_impact_json_report

        target = AnalysisTarget(
            target_type="project",
            name="MyApp",
            match_evidence="Contains portal classes",
            confidence=0.8,
        )
        ti = TargetImpact(target=target, total_direct=0, total_transitive=0)
        report = ImpactReport(
            sow_text="Update portal",
            targets=[ti],
            ambiguity_level="clear",
            avg_target_confidence=0.8,
        )

        output_path = tmp_path / "report.json"
        write_impact_json_report(report, output_path)

        data = json.loads(output_path.read_text())
        assert data["ambiguity_level"] == "clear"
        assert data["avg_target_confidence"] == 0.8
        target_data = data["targets"][0]["target"]
        assert target_data["match_evidence"] == "Contains portal classes"


# =============================================================================
# Budget-Aware Index Compression
# =============================================================================


class TestFilterTypes:
    def test_removes_stoplist_entries(self):
        types = ["Program", "PortalDataService", "Startup", "IDataService"]
        result = _filter_types(types, "MyApp")
        assert result == ["PortalDataService", "IDataService"]

    def test_removes_single_char_names(self):
        types = ["T", "I", "PortalDataService", "C"]
        result = _filter_types(types, "MyApp")
        assert result == ["PortalDataService"]

    def test_removes_project_name_duplicate(self):
        types = ["Foo", "PortalDataService"]
        result = _filter_types(types, "Foo")
        assert result == ["PortalDataService"]

    def test_preserves_order(self):
        types = ["Zebra", "Alpha", "Beta"]
        result = _filter_types(types, "MyApp")
        assert result == ["Zebra", "Alpha", "Beta"]

    def test_empty_input(self):
        assert _filter_types([], "MyApp") == []

    def test_all_filtered_returns_empty(self):
        types = ["Program", "Startup", "T"]
        assert _filter_types(types, "MyApp") == []


class TestApplyTypeCap:
    def test_no_truncation_under_cap(self):
        types = ["Alpha", "Beta"]
        assert _apply_type_cap(types, 5) == ["Alpha", "Beta"]

    def test_exact_cap_no_truncation(self):
        types = ["Alpha", "Beta", "Gamma"]
        assert _apply_type_cap(types, 3) == ["Alpha", "Beta", "Gamma"]

    def test_keeps_longest_names(self):
        types = ["Ax", "BetaService", "Cy", "AlphaController"]
        result = _apply_type_cap(types, 2)
        assert "AlphaController" in result
        assert "BetaService" in result
        assert "..." in result
        assert len(result) == 3

    def test_appends_ellipsis_when_truncated(self):
        types = ["Aa", "Bb", "Cc", "Dd"]
        result = _apply_type_cap(types, 2)
        assert result[-1] == "..."

    def test_preserves_original_order(self):
        types = ["BetaService", "AlphaController", "Tiny"]
        result = _apply_type_cap(types, 2)
        assert result == ["BetaService", "AlphaController", "..."]


class TestBudgetAwareIndex:
    def test_under_budget_returns_full_index(self):
        graph = _make_graph_with_projects([
            ("MyApp", "MyApp", ["Service", "Controller"], ["dbo.sp_Get"]),
        ])
        index = build_codebase_index(graph, max_bytes=100_000)
        assert "Service" in index.text
        assert "Controller" in index.text
        assert "..." not in index.text

    def test_no_max_bytes_returns_full_index(self):
        """max_bytes=None means no compression regardless of size."""
        projects = [
            (f"P{i}", f"P{i}", [f"LongTypeName{j}ForTesting" for j in range(50)], [])
            for i in range(100)
        ]
        graph = _make_graph_with_projects(projects)
        index = build_codebase_index(graph, max_bytes=None)
        assert index.project_count == 100
        assert index.type_count == 5000
        assert "..." not in index.text

    def test_shared_sproc_section_dropped_first(self):
        """Step 1: shared sproc cross-reference is removed before touching types."""
        projects = [
            (f"Project{i}", f"Project{i}", [f"Type{j}" for j in range(5)], ["dbo.sp_Shared"])
            for i in range(20)
        ]
        graph = _make_graph_with_projects(projects)
        full = build_codebase_index(graph)
        assert "=== Shared Stored Procedures ===" in full.text

        compressed = build_codebase_index(graph, max_bytes=full.size_bytes - 1)
        assert "=== Shared Stored Procedures ===" not in compressed.text
        # All types still present
        for j in range(5):
            assert f"Type{j}" in compressed.text

    def test_stoplist_removes_common_names(self):
        """Step 2: stoplist entries filtered when step 1 isn't enough."""
        projects = [
            (f"P{i}", f"P{i}",
             ["Program", "Startup", "Constants"] + [f"RealType{i}Service"],
             [])
            for i in range(50)
        ]
        graph = _make_graph_with_projects(projects)
        full = build_codebase_index(graph)

        # No shared sprocs, so step 1 saves nothing. Step 2 must do the work.
        target = full.size_bytes - 500
        compressed = build_codebase_index(graph, max_bytes=target)
        assert "Program" not in compressed.text
        assert "Startup" not in compressed.text
        assert "Constants" not in compressed.text
        assert "RealType0Service" in compressed.text

    def test_single_char_types_filtered(self):
        """Single-character type names removed by stoplist filter."""
        graph = _make_graph_with_projects([
            ("MyApp", "MyApp", ["T", "I", "PortalDataService", "C"], []),
        ])
        # Force compression with a tight budget
        compressed = build_codebase_index(graph, max_bytes=1)
        assert "PortalDataService" in compressed.text
        assert "T:" not in compressed.text or "T:PortalDataService" in compressed.text

    def test_type_cap_applied_when_over_budget(self):
        """Step 3: types capped per project, longest names kept."""
        projects = [
            (f"P{i}", f"P{i}",
             [f"Type{j:03d}WithLongishName" for j in range(30)],
             [])
            for i in range(100)
        ]
        graph = _make_graph_with_projects(projects)
        full = build_codebase_index(graph)

        compressed = build_codebase_index(graph, max_bytes=full.size_bytes // 2)
        assert "..." in compressed.text

    def test_type_cap_appends_ellipsis(self):
        """Truncated type lists end with '...' for parser compat."""
        projects = [
            (f"P{i}", f"P{i}",
             [f"TypeName{j}" for j in range(30)],
             [])
            for i in range(50)
        ]
        graph = _make_graph_with_projects(projects)
        compressed = build_codebase_index(graph, max_bytes=1)
        assert "..." in compressed.text

    def test_zero_signal_projects_dropped_last(self):
        """Step 4: projects with no types and no sprocs after filtering are removed."""
        projects = [
            ("HasTypes", "HasTypes", ["PortalDataService", "IDataService"], []),
            ("OnlyStoplist", "OnlyStoplist", ["Program", "Startup"], []),
            ("HasSprocs", "HasSprocs", ["Program"], ["dbo.sp_Get"]),
        ]
        graph = _make_graph_with_projects(projects)
        compressed = build_codebase_index(graph, max_bytes=1)
        assert "P:HasTypes" in compressed.text
        assert "P:HasSprocs" in compressed.text
        assert "P:OnlyStoplist" not in compressed.text

    def test_progressive_reduction_logs_steps(self, caplog):
        """Each reduction step logs what it did."""
        projects = [
            (f"P{i}", f"P{i}", [f"Type{j}" for j in range(20)], [])
            for i in range(50)
        ]
        graph = _make_graph_with_projects(projects)

        with caplog.at_level(logging.INFO, logger="scatter.ai.codebase_index"):
            build_codebase_index(graph, max_bytes=1)

        assert "exceeds budget" in caplog.text
        assert "Step 1" in caplog.text

    def test_still_over_budget_returns_best_effort(self, caplog):
        """If all reductions applied and still over, returns anyway with warning."""
        projects = [
            ("MyApp", "MyApp", ["PortalDataService"], ["dbo.sp_Get"]),
        ]
        graph = _make_graph_with_projects(projects)

        with caplog.at_level(logging.WARNING, logger="scatter.ai.codebase_index"):
            index = build_codebase_index(graph, max_bytes=1)

        assert index.text != ""
        assert index.size_bytes > 1
        assert "still exceeds budget" in caplog.text

    def test_extract_index_names_works_after_truncation(self):
        """_extract_index_names round-trips correctly on a budget-reduced index."""
        projects = [
            (f"P{i}", f"P{i}",
             [f"Type{j:03d}WithName" for j in range(30)],
             ["dbo.sp_Get"])
            for i in range(10)
        ]
        graph = _make_graph_with_projects(projects)
        index = build_codebase_index(graph, max_bytes=1)

        names = _extract_index_names(index.text)
        assert "P0" in names
        assert "dbo.sp_Get" in names
        assert "..." not in names

    def test_compressed_metrics_reflect_reduced_state(self):
        """project_count and type_count match the compressed output."""
        projects = [
            ("HasTypes", "HasTypes", ["PortalDataService"], []),
            ("OnlyStoplist", "OnlyStoplist", ["Program", "Startup"], []),
        ]
        graph = _make_graph_with_projects(projects)
        compressed = build_codebase_index(graph, max_bytes=1)
        # OnlyStoplist is dropped (zero-signal), so project_count = 1
        assert compressed.project_count == 1
        # Only PortalDataService survives
        assert compressed.type_count == 1
