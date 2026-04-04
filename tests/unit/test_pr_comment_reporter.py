"""Tests for PR comment markdown reporter with golden file snapshots.

Set UPDATE_GOLDEN=1 to regenerate golden files:
    UPDATE_GOLDEN=1 pytest tests/unit/test_pr_comment_reporter.py
"""

import os
from pathlib import Path

import pytest

from scatter.core.models import ChangedType, PRRiskReport
from scatter.core.risk_models import (
    AggregateRisk,
    RiskDimension,
    RiskLevel,
    RiskProfile,
)
from scatter.reports.pr_comment_reporter import build_pr_risk_markdown

GOLDEN_DIR = Path(__file__).parent.parent / "golden"
UPDATE_GOLDEN = os.environ.get("UPDATE_GOLDEN", "0") == "1"


def _assert_golden(actual: str, golden_name: str) -> None:
    """Compare actual output to golden file, optionally updating it."""
    golden_path = GOLDEN_DIR / golden_name
    if UPDATE_GOLDEN:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
        return

    if not golden_path.exists():
        # First run — create the golden file
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
        return

    expected = golden_path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"Output does not match golden file {golden_name}.\nRun with UPDATE_GOLDEN=1 to regenerate."
    )


def _green_report() -> PRRiskReport:
    """Low risk, few changes."""
    ct = ChangedType(
        name="NewService",
        kind="class",
        change_kind="added",
        owning_project="MyProject",
        owning_project_path="MyProject/MyProject.csproj",
        file_path="MyProject/NewService.cs",
    )
    cs_dim = RiskDimension(
        name="change_surface",
        label="Change surface",
        score=0.1,
        severity="low",
        factors=["1 type(s) added: NewService"],
        raw_metrics={"total_changes": 1, "additions": 1},
        data_available=True,
    )
    profile = RiskProfile(
        target_name="MyProject",
        target_type="project",
        change_surface=cs_dim,
        composite_score=0.09,
        risk_level=RiskLevel.GREEN,
        risk_factors=["1 type(s) added: NewService"],
    )
    agg = AggregateRisk(
        profiles=[profile],
        change_surface=cs_dim,
        composite_score=0.09,
        risk_level=RiskLevel.GREEN,
        risk_factors=["1 type(s) added: NewService"],
    )
    return PRRiskReport(
        branch_name="feature/add-service",
        base_branch="main",
        changed_types=[ct],
        aggregate=agg,
        profiles=[profile],
        graph_available=False,
        warnings=["Run with --search-scope to enable full graph-derived risk analysis."],
        duration_ms=42,
    )


def _red_report() -> PRRiskReport:
    """High risk, deletions, cycles."""
    ct1 = ChangedType(
        name="IDataAccess",
        kind="interface",
        change_kind="deleted",
        owning_project="Core",
        owning_project_path="Core/Core.csproj",
        file_path="Core/IDataAccess.cs",
    )
    ct2 = ChangedType(
        name="DataService",
        kind="class",
        change_kind="modified",
        owning_project="Core",
        owning_project_path="Core/Core.csproj",
        file_path="Core/DataService.cs",
    )
    cs_dim = RiskDimension(
        name="change_surface",
        label="Change surface",
        score=0.7,
        severity="high",
        factors=["1 type(s) deleted: IDataAccess", "1 type(s) modified: DataService"],
        raw_metrics={"total_changes": 2, "deletions": 1, "class_modifications": 1},
        data_available=True,
    )
    cycle_dim = RiskDimension(
        name="cycle",
        label="Cycle entanglement",
        score=0.8,
        severity="critical",
        factors=["Core is in a dependency cycle: Core → Api → Core (2 projects)"],
        raw_metrics={"cycle_count": 1},
        data_available=True,
    )
    profile = RiskProfile(
        target_name="Core",
        target_type="project",
        change_surface=cs_dim,
        cycle=cycle_dim,
        composite_score=0.8,
        risk_level=RiskLevel.RED,
        risk_factors=[
            "Core is in a dependency cycle: Core → Api → Core (2 projects)",
            "1 type(s) deleted: IDataAccess",
            "1 type(s) modified: DataService",
        ],
        consumer_count=5,
        transitive_consumer_count=3,
    )
    agg = AggregateRisk(
        profiles=[profile],
        change_surface=cs_dim,
        cycle=cycle_dim,
        composite_score=0.8,
        risk_level=RiskLevel.RED,
        risk_factors=[
            "Core is in a dependency cycle: Core → Api → Core (2 projects)",
            "1 type(s) deleted: IDataAccess",
            "1 type(s) modified: DataService",
        ],
    )
    return PRRiskReport(
        branch_name="feature/refactor-data",
        base_branch="main",
        changed_types=[ct1, ct2],
        aggregate=agg,
        profiles=[profile],
        total_direct_consumers=5,
        total_transitive_consumers=3,
        unique_consumers=["Api", "Worker", "Portal", "Reports", "Analytics"],
        graph_available=True,
        duration_ms=156,
    )


def _no_changes_report() -> PRRiskReport:
    """No C# type changes."""
    return PRRiskReport(
        branch_name="feature/docs-only",
        base_branch="main",
        changed_types=[],
        aggregate=AggregateRisk(profiles=[]),
        profiles=[],
        graph_available=True,
        duration_ms=5,
    )


class TestBuildPrRiskMarkdown:
    def test_green_snapshot(self):
        md = build_pr_risk_markdown(_green_report())
        _assert_golden(md, "pr_risk_green.md")

    def test_red_snapshot(self):
        md = build_pr_risk_markdown(_red_report())
        _assert_golden(md, "pr_risk_red.md")

    def test_no_changes_snapshot(self):
        md = build_pr_risk_markdown(_no_changes_report())
        _assert_golden(md, "pr_risk_no_changes.md")

    def test_collapsible_wraps_details(self):
        md = build_pr_risk_markdown(_red_report(), collapsible=True)
        assert "<details>" in md
        assert "<summary>" in md

    def test_green_has_low_score(self):
        md = build_pr_risk_markdown(_green_report())
        assert "GREEN" in md
        assert "0.09" in md

    def test_red_has_risk_factors(self):
        md = build_pr_risk_markdown(_red_report())
        assert "Risk Factors" in md
        assert "cycle" in md.lower()

    def test_no_changes_is_green(self):
        md = build_pr_risk_markdown(_no_changes_report())
        assert "GREEN" in md
        assert "0 type(s)" in md
