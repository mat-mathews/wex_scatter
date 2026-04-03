"""End-to-end CLI tests.

Invoke scatter as a subprocess against the sample .NET projects.
These tests verify that the full CLI pipeline works — argument parsing,
mode dispatch, graph building, analysis, and output formatting.

No mocks. No monkeypatching. Real files, real analysis, real output.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
GALAXY_CSPROJ = REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
WEBPORTAL_CSPROJ = REPO_ROOT / "GalaxyWorks.WebPortal" / "GalaxyWorks.WebPortal.csproj"
MYDOTNET_CSPROJ = REPO_ROOT / "MyDotNetApp" / "MyDotNetApp.csproj"
EXCLUDE_CSPROJ = REPO_ROOT / "MyDotNetApp2.Exclude" / "MyDotNetApp2.Exclude.csproj"


def run_scatter(*args: str, expect_fail: bool = False) -> subprocess.CompletedProcess:
    """Run scatter CLI and return the result."""
    cmd = [sys.executable, "-m", "scatter", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    if not expect_fail:
        assert result.returncode == 0, (
            f"scatter exited with code {result.returncode}\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )
    return result


# ======================================================================
# Target Project Mode
# ======================================================================


class TestTargetProjectMode:
    """--target-project against the sample GalaxyWorks projects."""

    def test_galaxy_data_finds_consumers(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
        )
        assert "GalaxyWorks.Data" in r.stdout
        # Should find at least 4 consumers
        assert "consumer" in r.stdout.lower() or "Consumed by" in r.stdout

    def test_galaxy_data_consumer_names(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
        )
        for name in ["GalaxyWorks.WebPortal", "GalaxyWorks.BatchProcessor"]:
            assert name in r.stdout, f"Expected consumer {name} not found in output"

    def test_webportal_finds_consumers(self):
        r = run_scatter(
            "--target-project",
            str(WEBPORTAL_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
        )
        assert "GalaxyWorks.WebPortal" in r.stdout

    def test_mydotnet_finds_one_consumer(self):
        r = run_scatter(
            "--target-project",
            str(MYDOTNET_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
        )
        assert "MyDotNetApp.Consumer" in r.stdout

    def test_exclude_project_zero_consumers(self):
        r = run_scatter(
            "--target-project",
            str(EXCLUDE_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
        )
        assert "no consuming relationships found" in r.stdout.lower()

    def test_class_name_filter(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--class-name",
            "PortalDataService",
        )
        assert "PortalDataService" in r.stdout

    def test_json_output(self, tmp_path):
        out = tmp_path / "result.json"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "json",
            "--output-file",
            str(out),
        )
        data = json.loads(out.read_text())
        assert isinstance(data, dict)
        # Should have results
        results = data.get("all_results", [])
        assert len(results) > 0, "JSON output has no results"

    def test_csv_output(self, tmp_path):
        out = tmp_path / "result.csv"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "csv",
            "--output-file",
            str(out),
        )
        content = out.read_text()
        lines = content.strip().split("\n")
        assert len(lines) >= 2, "CSV should have header + at least 1 data row"

    def test_markdown_output(self, tmp_path):
        out = tmp_path / "result.md"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "markdown",
            "--output-file",
            str(out),
        )
        content = out.read_text()
        assert "GalaxyWorks.Data" in content
        assert "|" in content  # markdown tables

    def test_graph_metrics_flag(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--graph-metrics",
        )
        assert "score" in r.stdout.lower()

    def test_no_graph_flag(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--no-graph",
        )
        assert "GalaxyWorks.Data" in r.stdout

    def test_rebuild_graph_flag(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--rebuild-graph",
        )
        assert "GalaxyWorks.Data" in r.stdout


# ======================================================================
# Stored Procedure Mode
# ======================================================================


class TestStoredProcedureMode:
    """--stored-procedure against the sample projects."""

    def test_sproc_finds_consumers(self):
        r = run_scatter(
            "--stored-procedure",
            "dbo.sp_InsertPortalConfiguration",
            "--search-scope",
            str(REPO_ROOT),
        )
        assert "GalaxyWorks.Data" in r.stdout
        assert "consumer" in r.stdout.lower() or "Consumed by" in r.stdout

    def test_sproc_json_output(self, tmp_path):
        out = tmp_path / "sproc.json"
        run_scatter(
            "--stored-procedure",
            "dbo.sp_InsertPortalConfiguration",
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "json",
            "--output-file",
            str(out),
        )
        data = json.loads(out.read_text())
        assert isinstance(data, dict)

    def test_sproc_not_found(self):
        r = run_scatter(
            "--stored-procedure",
            "dbo.sp_DoesNotExist",
            "--search-scope",
            str(REPO_ROOT),
        )
        assert "no consuming relationships found" in r.stdout.lower()


# ======================================================================
# Graph Mode
# ======================================================================


class TestGraphMode:
    """--graph mode against the sample projects."""

    def test_graph_console_output(self):
        r = run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
        )
        assert "projects" in r.stdout.lower()
        assert "dependencies" in r.stdout.lower()

    def test_graph_json_output(self, tmp_path):
        out = tmp_path / "graph.json"
        run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "json",
            "--output-file",
            str(out),
        )
        data = json.loads(out.read_text())
        assert isinstance(data, dict)
        assert len(data) > 0, "Graph JSON output is empty"

    def test_graph_csv_output(self, tmp_path):
        out = tmp_path / "graph.csv"
        run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "csv",
            "--output-file",
            str(out),
        )
        content = out.read_text()
        lines = content.strip().split("\n")
        assert len(lines) >= 2

    def test_graph_mermaid_output(self):
        r = run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "mermaid",
        )
        assert "graph" in r.stdout.lower() or "--->" in r.stdout

    def test_graph_markdown_output(self, tmp_path):
        out = tmp_path / "graph.md"
        run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "markdown",
            "--output-file",
            str(out),
        )
        content = out.read_text()
        assert "|" in content
        assert "project" in content.lower() or "node" in content.lower()

    def test_graph_rebuild_flag(self):
        r = run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
            "--rebuild-graph",
        )
        assert "projects" in r.stdout.lower()

    def test_graph_with_topology(self, tmp_path):
        out = tmp_path / "topo.json"
        run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "json",
            "--output-file",
            str(out),
            "--include-graph-topology",
        )
        data = json.loads(out.read_text())
        assert isinstance(data, dict)


# ======================================================================
# Error Cases
# ======================================================================


class TestErrorCases:
    """Verify scatter fails gracefully with bad input."""

    def test_no_mode_selected(self):
        r = run_scatter("--search-scope", str(REPO_ROOT), expect_fail=True)
        assert r.returncode != 0

    def test_missing_search_scope_target(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            expect_fail=True,
        )
        assert r.returncode != 0

    def test_missing_search_scope_sproc(self):
        r = run_scatter(
            "--stored-procedure",
            "dbo.sp_Test",
            expect_fail=True,
        )
        assert r.returncode != 0

    def test_missing_search_scope_graph(self):
        r = run_scatter("--graph", expect_fail=True)
        assert r.returncode != 0

    def test_bad_target_path(self):
        r = run_scatter(
            "--target-project",
            "/nonexistent/path.csproj",
            "--search-scope",
            str(REPO_ROOT),
            expect_fail=True,
        )
        assert r.returncode != 0

    def test_mermaid_only_in_graph_mode(self):
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "mermaid",
            expect_fail=True,
        )
        assert r.returncode != 0

    def test_pipelines_not_in_graph_mode(self):
        r = run_scatter(
            "--graph",
            "--search-scope",
            str(REPO_ROOT),
            "--output-format",
            "pipelines",
            expect_fail=True,
        )
        assert r.returncode != 0


# ======================================================================
# Git Branch Mode
# ======================================================================


class TestGitBranchMode:
    """--branch-name mode. Uses the current repo's main branch."""

    def test_branch_analysis_runs(self):
        """Analyze main against main — should find 0 changes but not crash."""
        # CI shallow clones may not have the main branch ref available.
        import git

        try:
            repo = git.Repo(REPO_ROOT)
            repo.commit("main")
        except Exception:
            pytest.skip("main branch not available (shallow clone)")

        r = run_scatter(
            "--branch-name",
            "main",
            "--repo-path",
            str(REPO_ROOT),
            "--search-scope",
            str(REPO_ROOT),
        )
        # Should complete without error
        assert r.returncode == 0
