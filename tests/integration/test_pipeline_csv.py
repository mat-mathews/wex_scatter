"""Tests for the pipeline CSV generator and load_pipeline_csv()."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "config_repo_mini"
EXAMPLES_DIR = REPO_ROOT / "examples"

REQUIRED_COLUMNS = {"pipeline_name", "app_name", "source"}
VALID_SOURCES = {"host_json", "web_config", "exe_config", "heuristic", "manual"}


# ---------------------------------------------------------------------------
# Schema tests — run against the committed CSV
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


class TestPipelineCsvSchema:
    """Validate the committed pipeline_to_app_mapping.csv."""

    def test_file_exists(self):
        assert (EXAMPLES_DIR / "pipeline_to_app_mapping.csv").is_file()

    def test_required_columns(self):
        fieldnames, _ = _read_csv(EXAMPLES_DIR / "pipeline_to_app_mapping.csv")
        assert REQUIRED_COLUMNS.issubset(set(fieldnames))

    def test_no_empty_pipeline_names(self):
        _, rows = _read_csv(EXAMPLES_DIR / "pipeline_to_app_mapping.csv")
        for r in rows:
            assert r.get("pipeline_name", "").strip(), f"Empty pipeline_name in row: {r}"

    def test_no_empty_app_names(self):
        _, rows = _read_csv(EXAMPLES_DIR / "pipeline_to_app_mapping.csv")
        for r in rows:
            assert r.get("app_name", "").strip(), f"Empty app_name in row: {r}"

    def test_valid_source_values(self):
        _, rows = _read_csv(EXAMPLES_DIR / "pipeline_to_app_mapping.csv")
        for r in rows:
            source = r.get("source", "").strip()
            assert source in VALID_SOURCES, f"Invalid source '{source}' in row: {r}"

    def test_no_duplicate_pairs(self):
        _, rows = _read_csv(EXAMPLES_DIR / "pipeline_to_app_mapping.csv")
        pairs = [(r["app_name"], r["pipeline_name"]) for r in rows]
        assert len(pairs) == len(set(pairs)), "Duplicate (app_name, pipeline_name) pairs found"


class TestManualOverridesSchema:
    """Validate pipeline_manual_overrides.csv if it exists."""

    def test_required_columns(self):
        path = EXAMPLES_DIR / "pipeline_manual_overrides.csv"
        if not path.is_file():
            pytest.skip("no manual overrides file")
        fieldnames, _ = _read_csv(path)
        assert REQUIRED_COLUMNS.issubset(set(fieldnames))

    def test_all_rows_are_manual(self):
        path = EXAMPLES_DIR / "pipeline_manual_overrides.csv"
        if not path.is_file():
            pytest.skip("no manual overrides file")
        _, rows = _read_csv(path)
        for r in rows:
            if r.get("source", "").strip():
                assert r["source"].strip() == "manual", f"Non-manual source in overrides: {r}"


# ---------------------------------------------------------------------------
# Generator fixture test — run against config_repo_mini
# ---------------------------------------------------------------------------


class TestGeneratorAgainstFixture:
    """Run generate_pipeline_csv.py against the synthetic fixture."""

    def test_output_shape(self, tmp_path):
        output = tmp_path / "output.csv"
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "generate_pipeline_csv.py"),
                "--app-config-path",
                str(FIXTURE_DIR),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Generator failed: {result.stderr}"
        assert output.is_file()

        fieldnames, rows = _read_csv(output)
        assert REQUIRED_COLUMNS.issubset(set(fieldnames))

        # Fixture has 7 pipelines producing 8 rows (2 Pattern-B batch jobs)
        assert len(rows) == 8

        sources = [r["source"] for r in rows]
        assert sources.count("host_json") == 5
        assert sources.count("web_config") == 1
        assert sources.count("heuristic") == 2

    def test_pattern_a_has_both_names(self, tmp_path):
        output = tmp_path / "output.csv"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "generate_pipeline_csv.py"),
                "--app-config-path",
                str(FIXTURE_DIR),
                "--output",
                str(output),
            ],
            capture_output=True,
        )
        _, rows = _read_csv(output)
        pattern_a = [r for r in rows if r["pipeline_name"] == "cdh-pattern-a-az-cd"]
        assert len(pattern_a) == 1
        assert pattern_a[0]["app_name"] == "WexHealth.Apps.Web.EmployerPortal"
        assert pattern_a[0]["assembly_name"] == "WexHealth.Apps.Web.Employer.Portal"

    def test_pattern_b_emits_per_job(self, tmp_path):
        output = tmp_path / "output.csv"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "generate_pipeline_csv.py"),
                "--app-config-path",
                str(FIXTURE_DIR),
                "--output",
                str(output),
            ],
            capture_output=True,
        )
        _, rows = _read_csv(output)
        batch_rows = [r for r in rows if r["pipeline_name"] == "cdh-batchprocesses-az-cd"]
        assert len(batch_rows) == 2
        app_names = sorted(r["app_name"] for r in batch_rows)
        assert "WEXHealth.CDH.BatchProcesses.HSA.JobAlpha" in app_names
        assert "WEXHealth.CDH.BatchProcesses.HSA.JobBeta" in app_names

    def test_nav_pipelines_emitted_individually(self, tmp_path):
        output = tmp_path / "output.csv"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "generate_pipeline_csv.py"),
                "--app-config-path",
                str(FIXTURE_DIR),
                "--output",
                str(output),
            ],
            capture_output=True,
        )
        _, rows = _read_csv(output)
        nav_rows = [r for r in rows if "navpipe" in r["pipeline_name"]]
        assert len(nav_rows) == 2
        pipelines = sorted(r["pipeline_name"] for r in nav_rows)
        assert pipelines == ["cdh-navpipe-nav1-az-cd", "cdh-navpipe-nav2-az-cd"]

    def test_d_partial_uses_web_config(self, tmp_path):
        output = tmp_path / "output.csv"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "generate_pipeline_csv.py"),
                "--app-config-path",
                str(FIXTURE_DIR),
                "--output",
                str(output),
            ],
            capture_output=True,
        )
        _, rows = _read_csv(output)
        partial = [r for r in rows if r["pipeline_name"] == "pts-partial-az-cd"]
        assert len(partial) == 1
        assert partial[0]["source"] == "web_config"
        assert partial[0]["app_name"] == "WexHealth.PTS.Partial"


# ---------------------------------------------------------------------------
# load_pipeline_csv merge test
# ---------------------------------------------------------------------------


class TestLoadPipelineCsvMerge:
    """Test that load_pipeline_csv reads both files, manual wins on conflict."""

    def test_manual_overrides_win(self, tmp_path):
        # Crawled CSV: AppFoo → pipeline-a
        crawled = tmp_path / "pipeline_to_app_mapping.csv"
        crawled.write_text(
            "pipeline_name,app_name,assembly_name,source\n"
            "pipeline-a,AppFoo,,host_json\n"
            "pipeline-c,AppBar,,host_json\n"
        )
        # Manual CSV: AppFoo → pipeline-b (override)
        manual = tmp_path / "pipeline_manual_overrides.csv"
        manual.write_text(
            "pipeline_name,app_name,assembly_name,source\n"
            "pipeline-b,AppFoo,,manual\n"
            "pipeline-d,AppBaz,,manual\n"
        )

        from scatter.modes.setup import load_pipeline_csv

        result = load_pipeline_csv(crawled)
        assert result["AppFoo"] == "pipeline-b"  # manual wins
        assert result["AppBar"] == "pipeline-c"  # crawled preserved
        assert result["AppBaz"] == "pipeline-d"  # manual-only added

    def test_old_schema_still_works(self, tmp_path):
        old_csv = tmp_path / "pipeline_to_app_mapping.csv"
        old_csv.write_text(
            '"Pipeline Name","Application Artifact","Application Name"\n'
            '"my-pipeline","artifact","MyApp"\n'
        )
        from scatter.modes.setup import load_pipeline_csv

        result = load_pipeline_csv(old_csv)
        assert result["MyApp"] == "my-pipeline"
