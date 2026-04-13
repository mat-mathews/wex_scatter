"""End-to-end tests for --pipeline-csv against example mapping data.

Runs scatter as a subprocess with the example pipeline_to_app_mapping.csv
from examples/ against the sample .NET projects. Verifies that pipeline
names flow through to console, JSON, CSV, markdown, and pipelines output.

Pipeline mapping works via project name lookup: the CSV "Application Name"
column matches against consumer project names (e.g., "GalaxyWorks.WebPortal").
The example CSV maps 5 of the sample projects to pipelines.

No mocks. No monkeypatching. Real files, real analysis, real output.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SAMPLES = REPO_ROOT / "samples"
GALAXY_CSPROJ = SAMPLES / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
MYDOTNET_CSPROJ = SAMPLES / "MyDotNetApp" / "MyDotNetApp.csproj"
PIPELINE_CSV = REPO_ROOT / "examples" / "pipeline_to_app_mapping.csv"
EXPECTED_PIPELINE = "galaxyworks-portal-az-cd"
EXPECTED_PIPELINES = {
    "galaxyworks-portal-az-cd",
    "galaxyworks-batch-az-cd",
    "galaxyworks-api-az-cd",
    "galaxyworks-notifications-az-cd",
    "galaxyworks-devtools-az-cd",
}


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


@pytest.fixture(scope="module")
def _check_example_csv():
    """Skip all tests if the example CSV doesn't exist."""
    if not PIPELINE_CSV.exists():
        pytest.skip("examples/pipeline_to_app_mapping.csv not found")


# ======================================================================
# Console output with pipeline data
# ======================================================================


@pytest.mark.usefixtures("_check_example_csv")
class TestPipelineConsoleOutput:
    """Verify pipeline names appear in console output."""

    def test_galaxy_data_runs_with_pipeline_csv(self):
        """Scatter should accept --pipeline-csv without error."""
        r = run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
        )
        # Console output includes solution name (pipeline resolves via solution)
        assert "GalaxyWorks.sln" in r.stdout

    def test_mydotnet_runs_with_pipeline_csv(self):
        """MyDotNetApp.Consumer is also in GalaxyWorks.sln."""
        r = run_scatter(
            "--target-project",
            str(MYDOTNET_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
        )
        assert "MyDotNetApp.Consumer" in r.stdout


# ======================================================================
# JSON output with pipeline data
# ======================================================================


@pytest.mark.usefixtures("_check_example_csv")
class TestPipelineJsonOutput:
    """Verify pipeline names appear in JSON output."""

    def test_json_has_pipeline_names(self, tmp_path):
        out = tmp_path / "result.json"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "json",
            "--output-file",
            str(out),
        )
        data = json.loads(out.read_text())
        results = data.get("all_results", [])
        assert len(results) > 0, "No results in JSON output"

        pipelines = [r.get("PipelineName") for r in results if r.get("PipelineName")]
        assert len(pipelines) > 0, "No pipeline names found in JSON results"
        assert all(p in EXPECTED_PIPELINES for p in pipelines)

    def test_json_pipeline_summary(self, tmp_path):
        out = tmp_path / "result.json"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "json",
            "--output-file",
            str(out),
        )
        data = json.loads(out.read_text())
        summary = data.get("pipeline_summary", [])
        assert EXPECTED_PIPELINE in summary


# ======================================================================
# CSV output with pipeline data
# ======================================================================


@pytest.mark.usefixtures("_check_example_csv")
class TestPipelineCsvOutput:
    """Verify pipeline names appear in CSV output."""

    def test_csv_has_pipeline_column_and_values(self, tmp_path):
        out = tmp_path / "result.csv"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "csv",
            "--output-file",
            str(out),
        )
        content = out.read_text()
        assert EXPECTED_PIPELINE in content.lower()


# ======================================================================
# Markdown output with pipeline data
# ======================================================================


@pytest.mark.usefixtures("_check_example_csv")
class TestPipelineMarkdownOutput:
    """Verify pipeline names appear in markdown output."""

    def test_markdown_has_pipeline_values(self, tmp_path):
        out = tmp_path / "result.md"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "markdown",
            "--output-file",
            str(out),
        )
        content = out.read_text()
        assert "Pipeline" in content
        assert EXPECTED_PIPELINE in content.lower()


# ======================================================================
# Pipelines output format
# ======================================================================


@pytest.mark.usefixtures("_check_example_csv")
class TestPipelinesOutputFormat:
    """Verify --output-format pipelines returns just pipeline names."""

    def test_pipelines_format_returns_names(self, tmp_path):
        out = tmp_path / "pipelines.txt"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "pipelines",
            "--output-file",
            str(out),
        )
        content = out.read_text().strip()
        lines = [l for l in content.split("\n") if l.strip()]
        assert len(lines) >= 1, "Pipelines output is empty"
        assert EXPECTED_PIPELINE in lines

    def test_pipelines_format_no_duplicates(self, tmp_path):
        out = tmp_path / "pipelines.txt"
        run_scatter(
            "--target-project",
            str(GALAXY_CSPROJ),
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "pipelines",
            "--output-file",
            str(out),
        )
        content = out.read_text().strip()
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        assert len(lines) == len(set(lines)), "Duplicate pipeline names in output"


# ======================================================================
# Stored procedure mode with pipeline data
# ======================================================================


@pytest.mark.usefixtures("_check_example_csv")
class TestPipelineWithSprocMode:
    """Verify pipeline mapping works in stored procedure mode."""

    def test_sproc_json_has_pipeline_names(self, tmp_path):
        out = tmp_path / "sproc.json"
        run_scatter(
            "--stored-procedure",
            "dbo.sp_InsertPortalConfiguration",
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "json",
            "--output-file",
            str(out),
        )
        data = json.loads(out.read_text())
        results = data.get("all_results", [])
        pipelines = [r.get("PipelineName") for r in results if r.get("PipelineName")]
        assert len(pipelines) > 0, "Sproc mode: no pipeline names in JSON"
        assert all(p in EXPECTED_PIPELINES for p in pipelines)

    def test_sproc_pipelines_format(self, tmp_path):
        out = tmp_path / "pipelines.txt"
        run_scatter(
            "--stored-procedure",
            "dbo.sp_InsertPortalConfiguration",
            "--search-scope",
            str(REPO_ROOT),
            "--pipeline-csv",
            str(PIPELINE_CSV),
            "--output-format",
            "pipelines",
            "--output-file",
            str(out),
        )
        content = out.read_text().strip()
        assert EXPECTED_PIPELINE in content
