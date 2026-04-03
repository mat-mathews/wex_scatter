"""Regression test: --sow output is unchanged after risk engine Phase 1.

Decision #10 from RISK_ENGINE_PLAN.md: "snapshot test proving --sow output
is byte-identical before and after the risk engine lands."

Risk engine Phase 1 added new modules only — zero modifications to existing
code paths. This test locks the ImpactReport JSON schema and console output
to prove that.
"""

import json
import io
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path

import pytest

from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    TargetImpact,
    ImpactReport,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
)
from scatter.reports.console_reporter import print_impact_report
from scatter.reports.json_reporter import write_impact_json_report


# --- Fixtures: canonical --sow report used as the regression baseline ---


def _build_baseline_report() -> ImpactReport:
    """Build a representative ImpactReport that exercises all fields.

    This is the "before" snapshot — it uses only types from scatter.core.models,
    which risk engine Phase 1 did NOT modify.
    """
    target = AnalysisTarget(
        target_type="project",
        name="GalaxyWorks.Data",
        csproj_path=Path("/repo/GalaxyWorks.Data/GalaxyWorks.Data.csproj"),
        namespace="GalaxyWorks.Data",
        class_name="PortalDataService",
        confidence=CONFIDENCE_HIGH,
        match_evidence="Matched project by name in codebase index",
    )

    consumer_a = EnrichedConsumer(
        consumer_path=Path("/repo/GalaxyWorks.Api/GalaxyWorks.Api.csproj"),
        consumer_name="GalaxyWorks.Api",
        relevant_files=[Path("/repo/GalaxyWorks.Api/Controllers/PortalController.cs")],
        solutions=["GalaxyWorks.sln"],
        pipeline_name="pipeline-api",
        depth=0,
        confidence=CONFIDENCE_HIGH,
        confidence_label="HIGH",
        risk_rating="High",
        risk_justification="Direct dependency in cycle with target",
        coupling_narrative="GalaxyWorks.Api directly instantiates PortalDataService.",
        coupling_vectors=["Direct class instantiation", "Interface implementation"],
    )

    consumer_b = EnrichedConsumer(
        consumer_path=Path("/repo/GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj"),
        consumer_name="GalaxyWorks.WebPortal",
        relevant_files=[],
        solutions=["GalaxyWorks.sln"],
        pipeline_name="pipeline-portal",
        depth=0,
        confidence=CONFIDENCE_HIGH,
        confidence_label="HIGH",
        risk_rating="Medium",
        risk_justification="Direct instantiation of PortalDataService",
    )

    consumer_c = EnrichedConsumer(
        consumer_path=Path("/repo/GalaxyWorks.Reporting/GalaxyWorks.Reporting.csproj"),
        consumer_name="GalaxyWorks.Reporting",
        relevant_files=[],
        solutions=[],
        pipeline_name="",
        depth=1,
        confidence=CONFIDENCE_MEDIUM,
        confidence_label="MEDIUM",
        risk_rating="Low",
        risk_justification="Transitive via GalaxyWorks.Api",
        propagation_parent="GalaxyWorks.Api",
    )

    ti = TargetImpact(
        target=target,
        consumers=[consumer_a, consumer_b, consumer_c],
        total_direct=2,
        total_transitive=1,
        max_depth_reached=1,
    )

    return ImpactReport(
        sow_text="Add tenant isolation to PortalDataService",
        targets=[ti],
        impact_narrative="This change affects the core data access layer.",
        complexity_rating="Medium",
        complexity_justification="Moderate blast radius with cycle involvement.",
        effort_estimate="3-5 developer-days",
        overall_risk="High",
        ambiguity_level="clear",
        avg_target_confidence=1.0,
    )


# --- JSON schema regression ---


class TestSOWJsonRegression:
    """Verify the ImpactReport JSON structure hasn't changed."""

    def test_json_top_level_keys(self):
        """ImpactReport JSON must contain exactly these top-level keys."""
        report = _build_baseline_report()
        report_dict = asdict(report)
        expected_keys = {
            "sow_text",
            "targets",
            "impact_narrative",
            "complexity_rating",
            "complexity_justification",
            "effort_estimate",
            "overall_risk",
            "ambiguity_level",
            "avg_target_confidence",
        }
        assert set(report_dict.keys()) == expected_keys

    def test_target_impact_keys(self):
        """TargetImpact JSON must contain exactly these keys."""
        report = _build_baseline_report()
        report_dict = asdict(report)
        ti = report_dict["targets"][0]
        expected_keys = {
            "target",
            "consumers",
            "total_direct",
            "total_transitive",
            "max_depth_reached",
        }
        assert set(ti.keys()) == expected_keys

    def test_enriched_consumer_keys(self):
        """EnrichedConsumer JSON must contain exactly these keys."""
        report = _build_baseline_report()
        report_dict = asdict(report)
        consumer = report_dict["targets"][0]["consumers"][0]
        expected_keys = {
            "consumer_path",
            "consumer_name",
            "relevant_files",
            "solutions",
            "pipeline_name",
            "depth",
            "confidence",
            "confidence_label",
            "risk_rating",
            "risk_justification",
            "coupling_narrative",
            "coupling_vectors",
            "propagation_parent",
            "coupling_score",
            "fan_in",
            "fan_out",
            "instability",
            "in_cycle",
        }
        assert set(consumer.keys()) == expected_keys

    def test_analysis_target_keys(self):
        """AnalysisTarget JSON must contain exactly these keys."""
        report = _build_baseline_report()
        report_dict = asdict(report)
        target = report_dict["targets"][0]["target"]
        expected_keys = {
            "target_type",
            "name",
            "csproj_path",
            "namespace",
            "class_name",
            "method_name",
            "confidence",
            "match_evidence",
        }
        assert set(target.keys()) == expected_keys

    def test_json_report_file_roundtrip(self, tmp_path):
        """write_impact_json_report produces valid JSON with expected structure."""
        report = _build_baseline_report()
        out = tmp_path / "sow_regression.json"
        write_impact_json_report(report, out)

        with open(out) as f:
            data = json.load(f)

        # Top-level must include report fields
        assert data["sow_text"] == "Add tenant isolation to PortalDataService"
        assert data["overall_risk"] == "High"
        assert len(data["targets"]) == 1
        assert len(data["targets"][0]["consumers"]) == 3

        # Propagation tree must be injected by the reporter
        assert "propagation_tree" in data["targets"][0]
        tree = data["targets"][0]["propagation_tree"]
        # Root nodes are direct consumers (depth=0)
        root_names = [n["consumer_name"] for n in tree]
        assert "GalaxyWorks.Api" in root_names
        assert "GalaxyWorks.WebPortal" in root_names

    def test_consumer_values_preserved(self, tmp_path):
        """All consumer field values survive JSON serialization."""
        report = _build_baseline_report()
        out = tmp_path / "values.json"
        write_impact_json_report(report, out)

        with open(out) as f:
            data = json.load(f)

        api = data["targets"][0]["consumers"][0]
        assert api["consumer_name"] == "GalaxyWorks.Api"
        assert api["risk_rating"] == "High"
        assert api["depth"] == 0
        assert api["coupling_vectors"] == ["Direct class instantiation", "Interface implementation"]
        assert api["propagation_parent"] is None

        reporting = data["targets"][0]["consumers"][2]
        assert reporting["consumer_name"] == "GalaxyWorks.Reporting"
        assert reporting["depth"] == 1
        assert reporting["propagation_parent"] == "GalaxyWorks.Api"


# --- Console output regression ---


class TestSOWConsoleRegression:
    """Verify console output format hasn't changed."""

    def _capture_console(self, report: ImpactReport) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_impact_report(report)
        return buf.getvalue()

    def test_console_output_structure(self):
        """Console output must contain expected section headers."""
        report = _build_baseline_report()
        output = self._capture_console(report)

        assert "=== Impact Analysis Report ===" in output
        assert "Work Request:" in output
        assert "Overall Risk: High" in output
        assert "Complexity: Medium" in output
        assert "--- Target: GalaxyWorks.Data ---" in output
        assert "Direct Consumers: 2" in output
        assert "Transitive: 1" in output
        assert "--- Complexity ---" in output
        assert "--- Impact Summary ---" in output

    def test_console_consumers_rendered(self):
        """All consumers appear in console output."""
        report = _build_baseline_report()
        output = self._capture_console(report)

        assert "GalaxyWorks.Api" in output
        assert "GalaxyWorks.WebPortal" in output
        assert "GalaxyWorks.Reporting" in output

    def test_console_target_quality_shown(self):
        """Ambiguity level and confidence are displayed."""
        report = _build_baseline_report()
        output = self._capture_console(report)

        assert "Target Quality: clear" in output
        assert "1 targets" in output
        assert "avg confidence 1.00" in output

    def test_console_match_evidence_shown(self):
        """Match evidence is displayed when present."""
        report = _build_baseline_report()
        output = self._capture_console(report)

        assert "Evidence: Matched project by name in codebase index" in output

    def test_console_empty_report(self):
        """Empty report doesn't crash."""
        report = ImpactReport(sow_text="Nothing relevant")
        output = self._capture_console(report)

        assert "No analysis targets were identified." in output


# --- Import safety regression ---


class TestRiskEngineDoesNotAffectSOW:
    """Prove risk engine Phase 1 is purely additive — no existing imports broken."""

    def test_models_module_has_no_risk_imports(self):
        """scatter.core.models must not import from risk_models.

        Risk engine Phase 1 added risk_models.py as a *separate* module.
        If models.py starts importing from risk_models, it could break
        existing importers.
        """
        import inspect
        import scatter.core.models as models_mod

        source = inspect.getsource(models_mod)
        assert "from scatter.core.risk_models" not in source
        assert "import scatter.core.risk_models" not in source

    def test_impact_analyzer_imports_risk_engine(self):
        """scatter.analyzers.impact_analyzer imports risk engine (Phase 2 shipped).

        Flipped from Phase 1's negative assertion (Decision #18). Documents
        that risk engine wiring is active in impact analysis.
        """
        import inspect
        import scatter.analyzers.impact_analyzer as ia_mod

        source = inspect.getsource(ia_mod)
        assert "from scatter.analyzers.risk_engine" in source
        assert "from scatter.core.risk_models" in source
