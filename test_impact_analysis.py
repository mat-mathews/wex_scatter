"""Tests for Initiative 4: CSE Impact Analysis & AI Enrichment."""
import csv
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scatter

from scatter.core.models import (
    AnalysisTarget,
    ConsumerResult,
    EnrichedConsumer,
    TargetImpact,
    ImpactReport,
    FilterPipeline,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_LABELS,
    DEFAULT_MAX_DEPTH,
    _confidence_label,
)
from scatter.ai.base import AITaskType
from scatter.ai.tasks.parse_work_request import (
    parse_work_request,
    parse_work_request_with_model,
    _resolve_project_name,
)
from scatter.ai.tasks.risk_assess import assess_risk, assess_risk_with_model
from scatter.ai.tasks.coupling_narrative import explain_coupling, explain_coupling_with_model
from scatter.ai.tasks.impact_narrative import generate_impact_narrative, generate_narrative_with_model
from scatter.ai.tasks.complexity_estimate import estimate_complexity, estimate_complexity_with_model
from scatter.analyzers.impact_analyzer import (
    run_impact_analysis,
    trace_transitive_impact,
)
from scatter.reports.console_reporter import print_impact_report, render_tree
from scatter.reports.json_reporter import write_impact_json_report
from scatter.reports.csv_reporter import write_impact_csv_report
from scatter.core.tree import build_adjacency


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_target():
    return AnalysisTarget(
        target_type="project",
        name="GalaxyWorks.Data",
        csproj_path=Path("/repo/GalaxyWorks.Data/GalaxyWorks.Data.csproj"),
        namespace="GalaxyWorks.Data",
        class_name="PortalDataService",
        confidence=CONFIDENCE_HIGH,
    )


@pytest.fixture
def sample_consumers():
    return [
        EnrichedConsumer(
            consumer_path=Path("/repo/ConsumerA/ConsumerA.csproj"),
            consumer_name="ConsumerA",
            relevant_files=[Path("/repo/ConsumerA/Service.cs")],
            solutions=["MainSolution"],
            pipeline_name="pipeline-a",
            depth=0,
            confidence=CONFIDENCE_HIGH,
            confidence_label="HIGH",
            risk_rating="Medium",
            risk_justification="Uses PortalDataService directly",
            coupling_narrative="ConsumerA instantiates PortalDataService.",
            coupling_vectors=["Direct class instantiation"],
        ),
        EnrichedConsumer(
            consumer_path=Path("/repo/ConsumerB/ConsumerB.csproj"),
            consumer_name="ConsumerB",
            relevant_files=[],
            solutions=[],
            pipeline_name="",
            depth=1,
            confidence=CONFIDENCE_MEDIUM,
            confidence_label="MEDIUM",
            risk_rating="Low",
            risk_justification="Transitive dependency",
            propagation_parent="ConsumerA",
        ),
    ]


@pytest.fixture
def sample_report(sample_target, sample_consumers):
    ti = TargetImpact(
        target=sample_target,
        consumers=sample_consumers,
        total_direct=1,
        total_transitive=1,
        max_depth_reached=1,
    )
    return ImpactReport(
        sow_text="Modify PortalDataService to add new parameter",
        targets=[ti],
        impact_narrative="This change affects ConsumerA directly.",
        complexity_rating="Medium",
        complexity_justification="Moderate blast radius.",
        effort_estimate="3-5 developer-days",
        overall_risk="Medium",
    )


def _make_mock_model(response_text):
    """Create a mock model that returns given text from generate_content()."""
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_model.generate_content.return_value = mock_response
    return mock_model


def _make_mock_provider(response_text):
    """Create a mock AI provider with a mock model."""
    provider = MagicMock()
    provider.model = _make_mock_model(response_text)
    return provider


# =============================================================================
# Phase 4.1: Data Models & Constants
# =============================================================================

class TestDataModels:
    def test_analysis_target_construction(self):
        t = AnalysisTarget(target_type="project", name="MyProject")
        assert t.target_type == "project"
        assert t.name == "MyProject"
        assert t.csproj_path is None
        assert t.confidence == CONFIDENCE_HIGH

    def test_enriched_consumer_defaults(self):
        c = EnrichedConsumer(
            consumer_path=Path("/a/b.csproj"),
            consumer_name="B",
        )
        assert c.depth == 0
        assert c.confidence == CONFIDENCE_HIGH
        assert c.confidence_label == "HIGH"
        assert c.risk_rating is None
        assert c.relevant_files == []
        assert c.solutions == []

    def test_target_impact_construction(self):
        t = AnalysisTarget(target_type="sproc", name="dbo.sp_Test")
        ti = TargetImpact(target=t)
        assert ti.total_direct == 0
        assert ti.total_transitive == 0
        assert ti.consumers == []

    def test_impact_report_construction(self):
        r = ImpactReport(sow_text="Do something")
        assert r.sow_text == "Do something"
        assert r.targets == []
        assert r.impact_narrative is None
        assert r.complexity_rating is None

    def test_confidence_constants(self):
        assert CONFIDENCE_HIGH == 1.0
        assert CONFIDENCE_MEDIUM == 0.6
        assert CONFIDENCE_LOW == 0.3
        assert CONFIDENCE_LABELS[1.0] == "HIGH"

    def test_confidence_label_function(self):
        assert _confidence_label(1.0) == "HIGH"
        assert _confidence_label(0.8) == "MEDIUM"
        assert _confidence_label(0.6) == "MEDIUM"
        assert _confidence_label(0.3) == "LOW"
        assert _confidence_label(0.1) == "LOW"

    def test_default_max_depth(self):
        assert DEFAULT_MAX_DEPTH == 2


# =============================================================================
# Phase 4.1: CLI Argument Parsing
# =============================================================================

class TestCLIArgs:
    def test_sow_in_mutually_exclusive_group(self, monkeypatch):
        """--sow and --branch-name should be mutually exclusive."""
        from scatter.__main__ import main
        monkeypatch.setattr(sys, "argv", ["scatter", "--sow", "test", "--branch-name", "feature/x"])
        with pytest.raises(SystemExit):
            main()

    def test_sow_file_in_mutually_exclusive_group(self, monkeypatch):
        """--sow-file and --target-project should be mutually exclusive."""
        from scatter.__main__ import main
        monkeypatch.setattr(sys, "argv", ["scatter", "--sow-file", "test.txt", "--target-project", "a.csproj"])
        with pytest.raises(SystemExit):
            main()

    def test_sow_requires_search_scope(self, monkeypatch):
        """--sow without --search-scope should error."""
        from scatter.__main__ import main
        monkeypatch.setattr(sys, "argv", ["scatter", "--sow", "test work request"])
        with pytest.raises(SystemExit):
            main()


# =============================================================================
# Phase 4.1: AITaskType Extensions
# =============================================================================

class TestAITaskTypes:
    def test_new_task_types_exist(self):
        assert AITaskType.WORK_REQUEST_PARSING.value == "work_request_parsing"
        assert AITaskType.RISK_ASSESSMENT.value == "risk_assessment"
        assert AITaskType.COUPLING_NARRATIVE.value == "coupling_narrative"
        assert AITaskType.IMPACT_NARRATIVE.value == "impact_narrative"
        assert AITaskType.COMPLEXITY_ESTIMATE.value == "complexity_estimate"

    def test_gemini_supports_new_types(self):
        from scatter.ai.providers.gemini_provider import GeminiProvider
        # Can't instantiate without API key, but we can check the method
        # by calling it on a mock instance
        provider = MagicMock(spec=GeminiProvider)
        provider.supports = GeminiProvider.supports.__get__(provider)
        assert provider.supports(AITaskType.WORK_REQUEST_PARSING)
        assert provider.supports(AITaskType.RISK_ASSESSMENT)
        assert provider.supports(AITaskType.IMPACT_NARRATIVE)
        assert provider.supports(AITaskType.COMPLEXITY_ESTIMATE)
        assert provider.supports(AITaskType.COUPLING_NARRATIVE)


# =============================================================================
# Phase 4.2: Work Request Parsing
# =============================================================================

class TestWorkRequestParsing:
    def test_parse_valid_json(self):
        response = json.dumps([
            {"type": "project", "name": "GalaxyWorks.Data", "class_name": "PortalDataService", "confidence": 0.9},
            {"type": "sproc", "name": "dbo.sp_InsertPortalConfiguration", "confidence": 1.0},
        ])
        model = _make_mock_model(response)
        result = parse_work_request_with_model(model, "Modify PortalDataService")
        assert result is not None
        assert len(result) == 2
        assert result[0]["name"] == "GalaxyWorks.Data"
        assert result[1]["type"] == "sproc"

    def test_parse_empty_array(self):
        model = _make_mock_model("[]")
        result = parse_work_request_with_model(model, "Some vague request")
        assert result == []

    def test_parse_invalid_json(self):
        model = _make_mock_model("not valid json at all")
        result = parse_work_request_with_model(model, "test")
        assert result is None

    def test_parse_non_list_json(self):
        model = _make_mock_model('{"not": "a list"}')
        result = parse_work_request_with_model(model, "test")
        assert result is None

    def test_parse_strips_markdown_fences(self):
        response = '```json\n[{"type": "project", "name": "MyApp", "confidence": 1.0}]\n```'
        model = _make_mock_model(response)
        result = parse_work_request_with_model(model, "test")
        assert result is not None
        assert len(result) == 1

    def test_parse_ai_exception(self):
        model = MagicMock()
        model.generate_content.side_effect = Exception("API error")
        result = parse_work_request_with_model(model, "test")
        assert result is None

    def test_resolve_project_name_exact(self):
        files = [
            Path("/repo/MyApp/MyApp.csproj"),
            Path("/repo/OtherApp/OtherApp.csproj"),
        ]
        assert _resolve_project_name("MyApp", files) == files[0]

    def test_resolve_project_name_case_insensitive(self):
        files = [Path("/repo/GalaxyWorks.Data/GalaxyWorks.Data.csproj")]
        assert _resolve_project_name("galaxyworks.data", files) == files[0]

    def test_resolve_project_name_partial(self):
        files = [Path("/repo/GalaxyWorks.Data/GalaxyWorks.Data.csproj")]
        assert _resolve_project_name("GalaxyWorks", files) == files[0]

    def test_resolve_project_name_not_found(self):
        files = [Path("/repo/SomeOther/SomeOther.csproj")]
        assert _resolve_project_name("NonExistent", files) is None

    def test_parse_work_request_no_provider(self):
        result = parse_work_request("some text", None, Path("/search"))
        assert result == []

    def test_parse_work_request_with_resolution(self, tmp_path):
        """Integration: parse_work_request resolves names to disk paths."""
        # Create a mock csproj
        proj_dir = tmp_path / "GalaxyWorks.Data"
        proj_dir.mkdir()
        csproj = proj_dir / "GalaxyWorks.Data.csproj"
        csproj.write_text("<Project></Project>")

        response = json.dumps([
            {"type": "project", "name": "GalaxyWorks.Data", "confidence": 1.0}
        ])
        provider = _make_mock_provider(response)

        targets = parse_work_request("Modify GalaxyWorks.Data", provider, tmp_path)
        assert len(targets) == 1
        assert targets[0].csproj_path == csproj
        assert targets[0].namespace == "GalaxyWorks.Data"


# =============================================================================
# Phase 4.3: Transitive Impact Tracing
# =============================================================================

class TestTransitiveTracing:
    def test_depth_zero_returns_direct_only(self):
        """With max_depth=0, only direct consumers returned."""
        direct = [
            {"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []},
        ]
        result = trace_transitive_impact(direct, Path("/search"), max_depth=0)
        assert len(result) == 1
        assert result[0].depth == 0
        assert result[0].confidence == CONFIDENCE_HIGH
        assert result[0].confidence_label == "HIGH"

    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    @patch("scatter.analyzers.impact_analyzer.derive_namespace")
    def test_depth_one_finds_transitive(self, mock_ns, mock_fc):
        """With max_depth=1, finds consumers of consumers."""
        mock_ns.return_value = "A.Namespace"
        mock_fc.return_value = (
            [{"consumer_path": Path("/b/B.csproj"), "consumer_name": "B", "relevant_files": []}],
            FilterPipeline(search_scope="/search", total_projects_scanned=0, total_files_scanned=0),
        )

        direct = [
            {"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []},
        ]
        # Make consumer path "exist" for the is_file() check
        with patch.object(Path, 'is_file', return_value=True):
            result = trace_transitive_impact(direct, Path("/search"), max_depth=1)

        assert len(result) == 2
        assert result[0].consumer_name == "A"
        assert result[0].depth == 0
        assert result[1].consumer_name == "B"
        assert result[1].depth == 1
        assert result[1].confidence == CONFIDENCE_MEDIUM

    def test_cycle_detection(self):
        """Consumers already visited should not be re-added."""
        direct = [
            {"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []},
        ]
        # Even with max_depth > 0, if find_consumers returns the same path, it's skipped
        with patch("scatter.analyzers.impact_analyzer.find_consumers") as mock_fc, \
             patch("scatter.analyzers.impact_analyzer.derive_namespace", return_value="A"), \
             patch.object(Path, 'is_file', return_value=True):
            # Return A again as a consumer of A (cycle)
            mock_fc.return_value = (
                [{"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []}],
                FilterPipeline(search_scope="/search", total_projects_scanned=0, total_files_scanned=0),
            )
            result = trace_transitive_impact(direct, Path("/search"), max_depth=2)

        assert len(result) == 1  # Only one instance of A

    def test_confidence_values_by_depth(self):
        """Confidence decays correctly at each depth."""
        with patch("scatter.analyzers.impact_analyzer.find_consumers") as mock_fc, \
             patch("scatter.analyzers.impact_analyzer.derive_namespace", return_value="NS"), \
             patch.object(Path, 'is_file', return_value=True):

            # Depth 0 → A, Depth 1 → B, Depth 2 → C
            _dummy_pipeline = FilterPipeline(search_scope="/search", total_projects_scanned=0, total_files_scanned=0)
            call_count = [0]
            def side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return ([{"consumer_path": Path("/b/B.csproj"), "consumer_name": "B", "relevant_files": []}], _dummy_pipeline)
                elif call_count[0] == 2:
                    return ([{"consumer_path": Path("/c/C.csproj"), "consumer_name": "C", "relevant_files": []}], _dummy_pipeline)
                return ([], _dummy_pipeline)

            mock_fc.side_effect = side_effect

            direct = [{"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []}]
            result = trace_transitive_impact(direct, Path("/search"), max_depth=2)

        assert len(result) == 3
        assert result[0].confidence == CONFIDENCE_HIGH    # depth 0
        assert result[1].confidence == CONFIDENCE_MEDIUM   # depth 1
        assert result[2].confidence == CONFIDENCE_LOW      # depth 2

    def test_empty_direct_consumers(self):
        result = trace_transitive_impact([], Path("/search"), max_depth=2)
        assert result == []


# =============================================================================
# Phase 4.4: Risk Assessment
# =============================================================================

class TestRiskAssessment:
    def test_valid_risk_response(self):
        response = json.dumps({
            "rating": "Medium",
            "justification": "Moderate blast radius",
            "concerns": ["Breaking changes"],
            "mitigations": ["Add integration tests"],
        })
        model = _make_mock_model(response)
        target = AnalysisTarget(target_type="project", name="TestProj")
        consumers = [EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A")]
        result = assess_risk_with_model(model, target, consumers)
        assert result["rating"] == "Medium"
        assert "concerns" in result

    def test_zero_consumers_returns_low(self):
        target = AnalysisTarget(target_type="project", name="TestProj")
        provider = _make_mock_provider("{}")
        result = assess_risk(target, [], provider)
        assert result["rating"] == "Low"

    def test_no_provider_returns_none(self):
        target = AnalysisTarget(target_type="project", name="TestProj")
        result = assess_risk(target, [], None)
        assert result is None

    def test_ai_failure_returns_none(self):
        model = MagicMock()
        model.generate_content.side_effect = Exception("fail")
        target = AnalysisTarget(target_type="project", name="TestProj")
        consumers = [EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A")]
        result = assess_risk_with_model(model, target, consumers)
        assert result is None

    def test_invalid_json_returns_none(self):
        model = _make_mock_model("not json")
        target = AnalysisTarget(target_type="project", name="TestProj")
        consumers = [EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A")]
        result = assess_risk_with_model(model, target, consumers)
        assert result is None


# =============================================================================
# Phase 4.5: Coupling Narrative & Impact Narrative
# =============================================================================

class TestCouplingNarrative:
    def test_valid_coupling_response(self):
        response = json.dumps({
            "narrative": "ConsumerA uses PortalDataService for data access.",
            "vectors": ["Direct class instantiation", "Method calls"],
        })
        model = _make_mock_model(response)
        target = AnalysisTarget(target_type="project", name="GalaxyWorks.Data")
        consumer = EnrichedConsumer(
            consumer_path=Path("/a.csproj"), consumer_name="A",
            relevant_files=[],
        )
        result = explain_coupling_with_model(model, target, consumer, ["// File: Test.cs\nclass Test {}"])
        assert result["narrative"] is not None
        assert "vectors" in result

    def test_no_relevant_files(self):
        target = AnalysisTarget(target_type="project", name="Test")
        consumer = EnrichedConsumer(
            consumer_path=Path("/a.csproj"), consumer_name="A",
            relevant_files=[],
        )
        provider = _make_mock_provider("{}")
        result = explain_coupling(target, consumer, provider, Path("/search"))
        assert result is None  # No files to read → None

    def test_no_provider_returns_none(self):
        target = AnalysisTarget(target_type="project", name="Test")
        consumer = EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A")
        result = explain_coupling(target, consumer, None, Path("/search"))
        assert result is None


class TestImpactNarrative:
    def test_valid_narrative_response(self):
        response = json.dumps({"narrative": "This change has moderate impact."})
        model = _make_mock_model(response)
        report = ImpactReport(sow_text="test", targets=[
            TargetImpact(
                target=AnalysisTarget(target_type="project", name="X"),
                consumers=[EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A")],
            )
        ])
        result = generate_narrative_with_model(model, report)
        assert result["narrative"] == "This change has moderate impact."

    def test_no_targets_returns_no_impact(self):
        provider = _make_mock_provider("{}")
        report = ImpactReport(sow_text="test")
        result = generate_impact_narrative(report, provider)
        assert "no impact" in result["narrative"].lower()

    def test_no_provider_returns_none(self):
        report = ImpactReport(sow_text="test")
        result = generate_impact_narrative(report, None)
        assert result is None

    def test_ai_failure_returns_none(self):
        model = MagicMock()
        model.generate_content.side_effect = Exception("fail")
        report = ImpactReport(sow_text="test", targets=[
            TargetImpact(target=AnalysisTarget(target_type="project", name="X"))
        ])
        result = generate_narrative_with_model(model, report)
        assert result is None


# =============================================================================
# Phase 4.6: Complexity Estimate
# =============================================================================

class TestComplexityEstimate:
    def test_valid_complexity_response(self):
        response = json.dumps({
            "rating": "Medium",
            "justification": "Moderate scope",
            "effort_estimate": "3-5 developer-days",
            "factors": ["Multiple consumers", "Pipeline dependencies"],
        })
        model = _make_mock_model(response)
        report = ImpactReport(sow_text="test", targets=[
            TargetImpact(
                target=AnalysisTarget(target_type="project", name="X"),
                consumers=[EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A")],
            )
        ])
        result = estimate_complexity_with_model(model, report)
        assert result["rating"] == "Medium"
        assert result["effort_estimate"] == "3-5 developer-days"

    def test_no_targets_returns_low(self):
        provider = _make_mock_provider("{}")
        report = ImpactReport(sow_text="test")
        result = estimate_complexity(report, provider)
        assert result["rating"] == "Low"

    def test_no_provider_returns_none(self):
        report = ImpactReport(sow_text="test")
        result = estimate_complexity(report, None)
        assert result is None


# =============================================================================
# Phase 4.7: Reporter Extensions
# =============================================================================

class TestConsoleReporter:
    def test_print_impact_report(self, sample_report, capsys):
        print_impact_report(sample_report)
        captured = capsys.readouterr().out
        assert "Impact Analysis Report" in captured
        assert "GalaxyWorks.Data" in captured
        assert "ConsumerA" in captured
        assert "ConsumerB" in captured
        assert "Medium" in captured
        assert "3-5 developer-days" in captured
        assert "Impact Summary" in captured
        # Tree view renders box-drawing characters
        assert "\u251c" in captured or "\u2514" in captured
        # Transitive consumer shows "via" label
        assert "via ConsumerA" in captured

    def test_print_empty_report(self, capsys):
        report = ImpactReport(sow_text="nothing here")
        print_impact_report(report)
        captured = capsys.readouterr().out
        assert "No analysis targets" in captured

    def test_print_report_truncates_long_sow(self, capsys):
        report = ImpactReport(sow_text="x" * 300)
        print_impact_report(report)
        captured = capsys.readouterr().out
        assert "..." in captured


class TestJsonReporter:
    def test_write_impact_json(self, sample_report, tmp_path):
        output = tmp_path / "report.json"
        write_impact_json_report(sample_report, output)
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["sow_text"] == sample_report.sow_text
        assert len(data["targets"]) == 1
        assert data["overall_risk"] == "Medium"
        # Verify Path objects serialized to strings
        consumer = data["targets"][0]["consumers"][0]
        assert isinstance(consumer["consumer_path"], str)

    def test_write_empty_report_json(self, tmp_path):
        output = tmp_path / "empty.json"
        report = ImpactReport(sow_text="empty")
        write_impact_json_report(report, output)
        data = json.loads(output.read_text())
        assert data["targets"] == []


class TestCsvReporter:
    def test_write_impact_csv(self, sample_report, tmp_path):
        output = tmp_path / "report.csv"
        write_impact_csv_report(sample_report, output)
        assert output.exists()
        with open(output, newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2  # 2 consumers
        assert rows[0]["Consumer"] == "ConsumerA"
        assert rows[0]["Depth"] == "0"
        assert rows[1]["Consumer"] == "ConsumerB"
        assert rows[1]["Depth"] == "1"
        # Check expected columns
        expected_cols = {'Target', 'TargetType', 'Consumer', 'ConsumerPath',
                         'Depth', 'PropagationParent', 'Confidence', 'ConfidenceLabel',
                         'RiskRating', 'RiskJustification', 'Pipeline',
                         'Solutions', 'CouplingVectors'}
        assert set(reader.fieldnames) == expected_cols

    def test_write_empty_report_csv(self, tmp_path):
        output = tmp_path / "empty.csv"
        report = ImpactReport(sow_text="empty")
        write_impact_csv_report(report, output)
        with open(output, newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 0


# =============================================================================
# Phase 4.8: End-to-End Integration (all AI mocked)
# =============================================================================

class TestEndToEnd:
    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    @patch("scatter.analyzers.impact_analyzer.derive_namespace")
    def test_full_pipeline_with_mocked_ai(self, mock_ns, mock_fc, tmp_path):
        """End-to-end: SOW → parse → find_consumers → transitive → enrich → report."""
        # Create a mock csproj on disk
        proj_dir = tmp_path / "GalaxyWorks.Data"
        proj_dir.mkdir()
        csproj = proj_dir / "GalaxyWorks.Data.csproj"
        csproj.write_text("<Project></Project>")

        consumer_dir = tmp_path / "ConsumerA"
        consumer_dir.mkdir()
        consumer_csproj = consumer_dir / "ConsumerA.csproj"
        consumer_csproj.write_text("<Project></Project>")

        mock_ns.return_value = "GalaxyWorks.Data"
        mock_fc.return_value = (
            [{"consumer_path": consumer_csproj, "consumer_name": "ConsumerA", "relevant_files": []}],
            FilterPipeline(search_scope=str(tmp_path), total_projects_scanned=0, total_files_scanned=0),
        )

        # Mock AI provider with responses for each task
        provider = MagicMock()

        # parse_work_request call
        parse_response = MagicMock()
        parse_response.text = json.dumps([
            {"type": "project", "name": "GalaxyWorks.Data", "class_name": "PortalDataService", "confidence": 1.0}
        ])

        # risk_assess call
        risk_response = MagicMock()
        risk_response.text = json.dumps({
            "rating": "Medium", "justification": "Moderate blast radius",
            "concerns": [], "mitigations": [],
        })

        # complexity call
        complexity_response = MagicMock()
        complexity_response.text = json.dumps({
            "rating": "Low", "justification": "Simple change",
            "effort_estimate": "1-2 developer-days", "factors": [],
        })

        # narrative call
        narrative_response = MagicMock()
        narrative_response.text = json.dumps({
            "narrative": "This is a low-impact change."
        })

        provider.model.generate_content.side_effect = [
            parse_response, risk_response, complexity_response, narrative_response,
        ]

        report = run_impact_analysis(
            sow_text="Modify PortalDataService in GalaxyWorks.Data",
            search_scope=tmp_path,
            ai_provider=provider,
            max_depth=0,
            disable_multiprocessing=True,
        )

        assert len(report.targets) == 1
        assert report.targets[0].target.name == "GalaxyWorks.Data"
        assert report.targets[0].total_direct == 1
        assert report.complexity_rating == "Low"
        assert report.effort_estimate == "1-2 developer-days"
        assert report.impact_narrative == "This is a low-impact change."

    def test_empty_sow_produces_empty_report(self, tmp_path):
        """Empty AI response produces an empty report gracefully."""
        provider = MagicMock()
        parse_response = MagicMock()
        parse_response.text = "[]"
        provider.model.generate_content.return_value = parse_response

        report = run_impact_analysis(
            sow_text="Something vague",
            search_scope=tmp_path,
            ai_provider=provider,
            max_depth=0,
        )

        assert len(report.targets) == 0
        assert report.overall_risk is None


# =============================================================================
# Quick Start Example Coverage Tests
# =============================================================================

class TestQuickStartTargetProjectExamples:
    """Tests covering every target-project Quick Start example in the README."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.test_root = Path(__file__).parent.resolve()

    def test_webportal_as_target(self):
        """README: --target-project GalaxyWorks.WebPortal → consumer includes BatchProcessor."""
        webportal_csproj = self.test_root / "GalaxyWorks.WebPortal" / "GalaxyWorks.WebPortal.csproj"
        assert webportal_csproj.exists(), f"WebPortal project not found: {webportal_csproj}"

        ns = scatter.derive_namespace(webportal_csproj)
        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=webportal_csproj,
            search_scope_path=self.test_root,
            target_namespace=ns,
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        consumer_names = {c["consumer_name"] for c in consumers}
        assert any("BatchProcessor" in name for name in consumer_names), \
            f"Expected a BatchProcessor consumer, got {consumer_names}"

    def test_mydotnetapp_as_target(self):
        """README: --target-project MyDotNetApp → consumer includes MyDotNetApp.Consumer."""
        mydotnetapp_csproj = self.test_root / "MyDotNetApp" / "MyDotNetApp.csproj"
        assert mydotnetapp_csproj.exists(), f"MyDotNetApp project not found: {mydotnetapp_csproj}"

        ns = scatter.derive_namespace(mydotnetapp_csproj)
        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=mydotnetapp_csproj,
            search_scope_path=self.test_root,
            target_namespace=ns,
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        consumer_names = {c["consumer_name"] for c in consumers}
        assert any("Consumer" in name for name in consumer_names), \
            f"Expected a Consumer project, got {consumer_names}"

    def test_exclude_project_zero_consumers(self):
        """README: --target-project MyDotNetApp2.Exclude → 0 consumers."""
        exclude_csproj = self.test_root / "MyDotNetApp2.Exclude" / "MyDotNetApp2.Exclude.csproj"
        assert exclude_csproj.exists(), f"Exclude project not found: {exclude_csproj}"

        ns = scatter.derive_namespace(exclude_csproj)
        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=exclude_csproj,
            search_scope_path=self.test_root,
            target_namespace=ns,
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        assert len(consumers) == 0, f"Expected 0 consumers for exclude project, got {len(consumers)}"


class TestQuickStartSprocExamples:
    """Tests covering stored procedure Quick Start examples."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.test_root = Path(__file__).parent.resolve()

    def test_sproc_get_portal_configuration_details(self):
        """README: --stored-procedure 'dbo.sp_GetPortalConfigurationDetails'."""
        sproc_results = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_GetPortalConfigurationDetails",
            search_path=self.test_root,
            disable_multiprocessing=True,
        )
        assert isinstance(sproc_results, dict)
        # Should find reference in GalaxyWorks.Data PortalDataService
        found_classes = []
        for project_path, classes_dict in sproc_results.items():
            found_classes.extend(classes_dict.keys())
        assert "PortalDataService" in found_classes, \
            f"Expected PortalDataService to reference sp_GetPortalConfigurationDetails, got {found_classes}"

    def test_sproc_with_class_filter(self):
        """README: --stored-procedure ... --class-name PortalDataService."""
        # find_cs_files_referencing_sproc doesn't take class_name directly,
        # but the CLI uses it to filter find_consumers results.
        # Test the full pipeline: sproc → project → find_consumers with class filter.
        sproc_results = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root,
            disable_multiprocessing=True,
        )
        assert isinstance(sproc_results, dict)
        assert len(sproc_results) > 0, "Should find at least one project with the sproc"

        # Now find consumers of the containing project with class filter
        for proj_path, classes_dict in sproc_results.items():
            if "PortalDataService" in classes_dict:
                ns = scatter.derive_namespace(proj_path)
                consumers, _pipeline = scatter.find_consumers(
                    target_csproj_path=proj_path,
                    search_scope_path=self.test_root,
                    target_namespace=ns,
                    class_name="PortalDataService",
                    method_name=None,
                    disable_multiprocessing=True,
                )
                assert len(consumers) > 0, \
                    "Should find consumers of PortalDataService via sproc pipeline"
                break
        else:
            pytest.fail("PortalDataService not found in sproc results")


class TestQuickStartOutputFormatExamples:
    """Tests covering output format Quick Start examples with real projects."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.test_root = Path(__file__).parent.resolve()
        self.galaxy_csproj = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"

    def test_json_output_with_target_project(self, tmp_path):
        """README: --output-format json --output-file for target project analysis."""
        from scatter.reports.json_reporter import prepare_detailed_results, write_json_report

        ns = scatter.derive_namespace(self.galaxy_csproj)
        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=self.galaxy_csproj,
            search_scope_path=self.test_root,
            target_namespace=ns,
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        assert len(consumers) > 0

        # Build results as ConsumerResult objects
        all_results = []
        for c in consumers:
            all_results.append(ConsumerResult(
                target_project_name="GalaxyWorks.Data",
                target_project_path=str(self.galaxy_csproj),
                triggering_type="TargetProject",
                consumer_project_name=c["consumer_name"],
                consumer_project_path=str(c["consumer_path"]),
            ))

        detailed = prepare_detailed_results(all_results)
        output_file = tmp_path / "results.json"
        write_json_report(detailed, output_file)
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "all_results" in data
        assert len(data["all_results"]) == len(consumers)

    def test_csv_output_with_target_project(self, tmp_path):
        """README: --output-format csv --output-file for target project analysis."""
        from scatter.reports.csv_reporter import write_csv_report

        ns = scatter.derive_namespace(self.galaxy_csproj)
        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=self.galaxy_csproj,
            search_scope_path=self.test_root,
            target_namespace=ns,
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        assert len(consumers) > 0

        all_results = []
        for c in consumers:
            all_results.append(ConsumerResult(
                target_project_name="GalaxyWorks.Data",
                target_project_path=str(self.galaxy_csproj),
                triggering_type="TargetProject",
                consumer_project_name=c["consumer_name"],
                consumer_project_path=str(c["consumer_path"]),
            ))

        from scatter.reports.json_reporter import prepare_detailed_results as _prep
        output_file = tmp_path / "results.csv"
        write_csv_report(_prep(all_results), output_file)
        assert output_file.exists()
        with open(output_file, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == len(consumers)


class TestQuickStartAIExamples:
    """Tests covering AI-powered Quick Start examples."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.test_root = Path(__file__).parent.resolve()

    def test_target_project_consumers_have_relevant_files(self):
        """Target project consumers include relevant_files for summarization."""
        galaxy_csproj = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        ns = scatter.derive_namespace(galaxy_csproj)
        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=galaxy_csproj,
            search_scope_path=self.test_root,
            target_namespace=ns,
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        assert len(consumers) > 0

        # Verify each consumer has relevant_files that could be summarized
        for c in consumers:
            assert "relevant_files" in c
            assert isinstance(c["relevant_files"], list)

    def test_sow_file_reads_from_disk(self, tmp_path):
        """--sow-file content flows through to impact analysis report."""
        sow_content = "Modify PortalDataService to add new parameter to sp_InsertPortalConfiguration"
        sow_file = tmp_path / "sow.txt"
        sow_file.write_text(sow_content, encoding="utf-8")

        # Load from disk as __main__.py does, then run impact analysis
        loaded_text = sow_file.resolve(strict=True).read_text(encoding="utf-8")

        provider = MagicMock()
        parse_response = MagicMock()
        parse_response.text = json.dumps([
            {"type": "project", "name": "GalaxyWorks.Data", "confidence": 1.0}
        ])
        provider.model.generate_content.return_value = parse_response

        report = run_impact_analysis(
            sow_text=loaded_text,
            search_scope=self.test_root,
            ai_provider=provider,
            max_depth=0,
            disable_multiprocessing=True,
        )
        assert report.sow_text == sow_content


# =============================================================================
# Initiative 6 Phase 3: Blast Radius Tree View
# =============================================================================


class TestBlastRadiusTreeView:
    """Tests for the blast radius tree view feature."""

    # -- 6a. Model tests --

    def test_enriched_consumer_has_propagation_parent(self):
        """propagation_parent field exists and defaults to None."""
        c = EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A")
        assert c.propagation_parent is None

    def test_enriched_consumer_with_parent(self):
        """propagation_parent can be set to a consumer name."""
        c = EnrichedConsumer(
            consumer_path=Path("/b.csproj"), consumer_name="B",
            depth=1, propagation_parent="A",
        )
        assert c.propagation_parent == "A"

    # -- 6b. BFS parent tracking tests --

    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    @patch("scatter.analyzers.impact_analyzer.derive_namespace")
    def test_transitive_tracing_sets_propagation_parent(self, mock_ns, mock_fc):
        """Transitive consumer gets propagation_parent set to its discoverer."""
        mock_ns.return_value = "A.Namespace"
        mock_fc.return_value = (
            [{"consumer_path": Path("/b/B.csproj"), "consumer_name": "B", "relevant_files": []}],
            FilterPipeline(search_scope="/search", total_projects_scanned=0, total_files_scanned=0),
        )
        direct = [
            {"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []},
        ]
        with patch.object(Path, 'is_file', return_value=True):
            result = trace_transitive_impact(direct, Path("/search"), max_depth=1)

        assert result[1].consumer_name == "B"
        assert result[1].propagation_parent == "A"

    def test_direct_consumers_have_no_parent(self):
        """Depth-0 consumers have propagation_parent is None."""
        direct = [
            {"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []},
        ]
        result = trace_transitive_impact(direct, Path("/search"), max_depth=0)
        assert len(result) == 1
        assert result[0].propagation_parent is None

    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    @patch("scatter.analyzers.impact_analyzer.derive_namespace")
    def test_cycle_detection_preserves_parent(self, mock_ns, mock_fc):
        """Cycle detection doesn't corrupt parent tracking."""
        mock_ns.return_value = "A.Namespace"
        mock_fc.return_value = (
            [{"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []}],
            FilterPipeline(search_scope="/search", total_projects_scanned=0, total_files_scanned=0),
        )
        direct = [
            {"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []},
        ]
        with patch.object(Path, 'is_file', return_value=True):
            result = trace_transitive_impact(direct, Path("/search"), max_depth=2)

        assert len(result) == 1
        assert result[0].propagation_parent is None  # direct, not re-added

    @patch("scatter.analyzers.impact_analyzer.find_consumers")
    @patch("scatter.analyzers.impact_analyzer.derive_namespace")
    def test_diamond_dependency_first_parent_wins(self, mock_ns, mock_fc):
        """When two direct consumers discover the same transitive, first discoverer is parent."""
        mock_ns.return_value = "NS"
        _dummy_pipeline = FilterPipeline(
            search_scope="/search", total_projects_scanned=0, total_files_scanned=0,
        )
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:  # Both A and B discover C
                return (
                    [{"consumer_path": Path("/c/C.csproj"), "consumer_name": "C", "relevant_files": []}],
                    _dummy_pipeline,
                )
            return ([], _dummy_pipeline)

        mock_fc.side_effect = side_effect

        direct = [
            {"consumer_path": Path("/a/A.csproj"), "consumer_name": "A", "relevant_files": []},
            {"consumer_path": Path("/b/B.csproj"), "consumer_name": "B", "relevant_files": []},
        ]
        with patch.object(Path, 'is_file', return_value=True):
            result = trace_transitive_impact(direct, Path("/search"), max_depth=1)

        assert len(result) == 3
        c = next(r for r in result if r.consumer_name == "C")
        assert c.propagation_parent == "A"  # first discoverer wins

    def test_orphan_parent_renders_at_root_as_direct(self):
        """If propagation_parent references removed consumer, renders at root level as 'direct'."""
        consumers = [
            EnrichedConsumer(
                consumer_path=Path("/a.csproj"), consumer_name="A", depth=0,
                confidence_label="HIGH",
            ),
            EnrichedConsumer(
                consumer_path=Path("/b.csproj"), consumer_name="B", depth=1,
                confidence_label="MEDIUM", propagation_parent="Removed",
            ),
        ]
        lines = render_tree(consumers)
        # B should render at root level (same indent as A) since "Removed" isn't a consumer
        a_line = next(l for l in lines if "A" in l and "HIGH" in l)
        b_line = next(l for l in lines if "B" in l and "MEDIUM" in l)
        a_indent = len(a_line) - len(a_line.lstrip())
        b_indent = len(b_line) - len(b_line.lstrip())
        assert a_indent == b_indent
        # Orphan shows as "direct", NOT "via Removed"
        assert "direct" in b_line
        assert "Removed" not in b_line

    def test_orphan_adjacency_falls_back_to_root(self):
        """build_adjacency re-parents orphans whose parent isn't in the item list."""
        consumers = [
            EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0),
            EnrichedConsumer(consumer_path=Path("/b.csproj"), consumer_name="B", depth=1, propagation_parent="Removed"),
        ]
        tree = build_adjacency(
            consumers,
            get_name=lambda c: c.consumer_name,
            get_parent=lambda c: c.propagation_parent,
        )
        root_names = [c.consumer_name for c in tree.get(None, [])]
        assert "A" in root_names
        assert "B" in root_names

    # -- 6c. Console tree rendering tests --

    def test_tree_output_single_target_direct_only(self):
        """3 direct consumers render with box-drawing chars."""
        consumers = [
            EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0, confidence=CONFIDENCE_HIGH, confidence_label="HIGH"),
            EnrichedConsumer(consumer_path=Path("/b.csproj"), consumer_name="B", depth=0, confidence=CONFIDENCE_MEDIUM, confidence_label="MEDIUM"),
            EnrichedConsumer(consumer_path=Path("/c.csproj"), consumer_name="C", depth=0, confidence=CONFIDENCE_LOW, confidence_label="LOW"),
        ]
        lines = render_tree(consumers)
        joined = "\n".join(lines)
        assert "\u251c\u2500\u2500" in joined  # branch connector
        assert "\u2514\u2500\u2500" in joined  # last-child connector
        assert "A" in joined
        assert "B" in joined
        assert "C" in joined

    def test_tree_output_mixed_depths(self):
        """1 direct + 1 transitive renders nested tree with 'via' label."""
        consumers = [
            EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0, confidence=CONFIDENCE_HIGH, confidence_label="HIGH"),
            EnrichedConsumer(consumer_path=Path("/b.csproj"), consumer_name="B", depth=1, confidence=CONFIDENCE_MEDIUM, confidence_label="MEDIUM", propagation_parent="A"),
        ]
        lines = render_tree(consumers)
        joined = "\n".join(lines)
        assert "via A" in joined
        assert "\u2502" in joined or "\u2514" in joined  # nesting chars

    def test_tree_output_empty_consumers(self):
        """No consumers produces no tree lines."""
        lines = render_tree([])
        assert lines == []

    def test_tree_output_deep_nesting(self):
        """Depth 0->1->2 chain renders 3-level tree."""
        consumers = [
            EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0, confidence=CONFIDENCE_HIGH, confidence_label="HIGH"),
            EnrichedConsumer(consumer_path=Path("/b.csproj"), consumer_name="B", depth=1, confidence=CONFIDENCE_MEDIUM, confidence_label="MEDIUM", propagation_parent="A"),
            EnrichedConsumer(consumer_path=Path("/c.csproj"), consumer_name="C", depth=2, confidence=CONFIDENCE_LOW, confidence_label="LOW", propagation_parent="B"),
        ]
        lines = render_tree(consumers)
        joined = "\n".join(lines)
        assert "A" in joined
        assert "via A" in joined
        assert "via B" in joined
        # C should be indented further than B
        b_line = next(l for l in lines if "B" in l and "via" in l)
        c_line = next(l for l in lines if "C" in l and "via" in l)
        # C's leading whitespace should be longer than B's
        b_indent = len(b_line) - len(b_line.lstrip())
        c_indent = len(c_line) - len(c_line.lstrip())
        assert c_indent > b_indent

    def test_tree_output_sorts_by_confidence(self):
        """HIGH consumers render before LOW within same parent."""
        consumers = [
            EnrichedConsumer(consumer_path=Path("/low.csproj"), consumer_name="Low", depth=0, confidence=CONFIDENCE_LOW, confidence_label="LOW"),
            EnrichedConsumer(consumer_path=Path("/high.csproj"), consumer_name="High", depth=0, confidence=CONFIDENCE_HIGH, confidence_label="HIGH"),
            EnrichedConsumer(consumer_path=Path("/med.csproj"), consumer_name="Med", depth=0, confidence=CONFIDENCE_MEDIUM, confidence_label="MEDIUM"),
        ]
        lines = render_tree(consumers)
        joined = "\n".join(lines)
        assert joined.index("High") < joined.index("Med") < joined.index("Low")

    def test_tree_no_duplicate_target_name(self, capsys):
        """Tree output should not repeat the target name (header already shows it)."""
        target = AnalysisTarget(target_type="project", name="MyTarget")
        consumer = EnrichedConsumer(
            consumer_path=Path("/a.csproj"), consumer_name="A", depth=0,
            confidence_label="HIGH",
        )
        ti = TargetImpact(target=target, consumers=[consumer], total_direct=1)
        report = ImpactReport(sow_text="test", targets=[ti])
        print_impact_report(report)
        captured = capsys.readouterr().out
        # Target name appears in header, not duplicated as tree root
        assert captured.count("MyTarget") == 1

    # -- 6d. JSON propagation_tree tests --

    def test_json_has_propagation_tree(self, tmp_path):
        """propagation_tree key exists in each target."""
        target = AnalysisTarget(target_type="project", name="X")
        consumer = EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0)
        ti = TargetImpact(target=target, consumers=[consumer], total_direct=1)
        report = ImpactReport(sow_text="test", targets=[ti])

        output = tmp_path / "report.json"
        write_impact_json_report(report, output)
        data = json.loads(output.read_text())
        assert "propagation_tree" in data["targets"][0]

    def test_json_propagation_tree_nesting(self, tmp_path):
        """Nested children structure matches BFS chain."""
        target = AnalysisTarget(target_type="project", name="X")
        consumers = [
            EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0, confidence_label="HIGH"),
            EnrichedConsumer(consumer_path=Path("/b.csproj"), consumer_name="B", depth=1, confidence_label="MEDIUM", propagation_parent="A"),
        ]
        ti = TargetImpact(target=target, consumers=consumers, total_direct=1, total_transitive=1)
        report = ImpactReport(sow_text="test", targets=[ti])

        output = tmp_path / "report.json"
        write_impact_json_report(report, output)
        data = json.loads(output.read_text())
        tree = data["targets"][0]["propagation_tree"]
        assert len(tree) == 1
        assert tree[0]["consumer_name"] == "A"
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["consumer_name"] == "B"

    def test_json_flat_consumers_preserved(self, tmp_path):
        """Backward-compat consumers[] array still present."""
        target = AnalysisTarget(target_type="project", name="X")
        consumer = EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0)
        ti = TargetImpact(target=target, consumers=[consumer], total_direct=1)
        report = ImpactReport(sow_text="test", targets=[ti])

        output = tmp_path / "report.json"
        write_impact_json_report(report, output)
        data = json.loads(output.read_text())
        assert "consumers" in data["targets"][0]
        assert len(data["targets"][0]["consumers"]) == 1

    def test_json_tree_sorted_by_confidence(self, tmp_path):
        """JSON propagation_tree sorts children HIGH before LOW, matching console."""
        target = AnalysisTarget(target_type="project", name="X")
        consumers = [
            EnrichedConsumer(consumer_path=Path("/low.csproj"), consumer_name="Low", depth=0, confidence_label="LOW"),
            EnrichedConsumer(consumer_path=Path("/high.csproj"), consumer_name="High", depth=0, confidence_label="HIGH"),
        ]
        ti = TargetImpact(target=target, consumers=consumers, total_direct=2)
        report = ImpactReport(sow_text="test", targets=[ti])

        output = tmp_path / "report.json"
        write_impact_json_report(report, output)
        data = json.loads(output.read_text())
        tree = data["targets"][0]["propagation_tree"]
        assert tree[0]["consumer_name"] == "High"
        assert tree[1]["consumer_name"] == "Low"

    # -- 6e. CSV tests --

    def test_csv_has_propagation_parent_column(self, tmp_path):
        """PropagationParent column exists in output."""
        target = AnalysisTarget(target_type="project", name="X")
        consumer = EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0)
        ti = TargetImpact(target=target, consumers=[consumer], total_direct=1)
        report = ImpactReport(sow_text="test", targets=[ti])

        output = tmp_path / "report.csv"
        write_impact_csv_report(report, output)
        with open(output, newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert 'PropagationParent' in reader.fieldnames

    def test_csv_propagation_parent_values(self, tmp_path):
        """Correct parent names in CSV rows."""
        target = AnalysisTarget(target_type="project", name="X")
        consumers = [
            EnrichedConsumer(consumer_path=Path("/a.csproj"), consumer_name="A", depth=0),
            EnrichedConsumer(consumer_path=Path("/b.csproj"), consumer_name="B", depth=1, propagation_parent="A"),
        ]
        ti = TargetImpact(target=target, consumers=consumers, total_direct=1, total_transitive=1)
        report = ImpactReport(sow_text="test", targets=[ti])

        output = tmp_path / "report.csv"
        write_impact_csv_report(report, output)
        with open(output, newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]['PropagationParent'] == ''
        assert rows[1]['PropagationParent'] == 'A'
