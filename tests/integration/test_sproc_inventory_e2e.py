"""End-to-end integration tests for --sproc-inventory mode."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCATTER_CMD = [sys.executable, "-m", "scatter"]
SAMPLES_DIR = str(Path(__file__).resolve().parent.parent.parent / "samples")


def _run(*args, expect_ok=True):
    result = subprocess.run(
        SCATTER_CMD + list(args),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if expect_ok:
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
    return result


class TestSprocInventoryMode:
    def test_end_to_end_console(self):
        """--sproc-inventory produces a console table with sproc data."""
        result = _run("--sproc-inventory", "--search-scope", SAMPLES_DIR)
        assert "Stored Procedure Inventory" in result.stdout
        assert "sp_InsertPortalConfiguration" in result.stdout
        assert "SQL definition coverage" in result.stdout

    def test_finds_sql_definitions(self):
        """Sprocs defined in .sql files show as 'defined + referenced'."""
        result = _run("--sproc-inventory", "--search-scope", SAMPLES_DIR)
        assert "defined + referenced" in result.stdout

    def test_labels_undefined_sprocs(self):
        """Sprocs without .sql files labeled 'no .sql definition in repo'."""
        result = _run("--sproc-inventory", "--search-scope", SAMPLES_DIR)
        assert "no .sql definition in repo" in result.stdout

    def test_json_output(self, tmp_path):
        """--output-format json produces valid JSON with expected fields."""
        out_file = tmp_path / "inventory.json"
        _run(
            "--sproc-inventory",
            "--search-scope",
            SAMPLES_DIR,
            "--output-format",
            "json",
            "--output-file",
            str(out_file),
        )
        data = json.loads(out_file.read_text())
        assert "total_sprocs" in data
        assert "entries" in data
        assert data["total_sprocs"] > 0
        # Check entry structure
        entry = data["entries"][0]
        assert "name" in entry
        assert "status" in entry
        assert "detection_methods" in entry

    def test_mutual_exclusion_with_stored_procedure(self):
        """--sproc-inventory and --stored-procedure cannot be used together."""
        result = _run(
            "--sproc-inventory",
            "--stored-procedure",
            "dbo.sp_Foo",
            "--search-scope",
            SAMPLES_DIR,
            expect_ok=False,
        )
        assert result.returncode != 0
        assert "not allowed" in result.stderr.lower() or "argument" in result.stderr.lower()

    def test_requires_search_scope(self):
        """--sproc-inventory needs --search-scope to know where to look."""
        result = _run("--sproc-inventory", expect_ok=False)
        # Should fail because no search scope means no files to scan
        # The graph build needs a search scope
        assert result.returncode != 0
