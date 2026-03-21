"""End-to-end validation tests for Initiative 9: Solution-Aware Graph.

These tests run scatter CLI commands against the sample projects and verify
solution data flows through all output formats correctly.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent


def _run_scatter(*args, **kwargs):
    """Run scatter as subprocess, return (returncode, stdout, stderr)."""
    cmd = [sys.executable, "-m", "scatter"] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(REPO_ROOT), timeout=60,
        **kwargs,
    )
    return result.returncode, result.stdout, result.stderr


class TestGraphModeSolutionOutput:
    def test_console_has_solution_sections(self):
        rc, stdout, _ = _run_scatter(
            "--graph", "--include-db", "--search-scope", ".",
            "--rebuild-graph",
        )
        assert rc == 0
        assert "Solutions:" in stdout
        assert "Solution Coupling" in stdout
        assert "Align" in stdout
        assert "(solution:" in stdout

    def test_json_has_solution_data(self, tmp_path):
        out = tmp_path / "graph.json"
        rc, _, _ = _run_scatter(
            "--graph", "--include-db", "--search-scope", ".",
            "--rebuild-graph", "--include-graph-topology",
            "--output-format", "json", "--output-file", str(out),
        )
        assert rc == 0
        data = json.loads(out.read_text())

        # Solution metrics section
        assert "solution_metrics" in data
        assert "GalaxyWorks" in data["solution_metrics"]
        gw = data["solution_metrics"]["GalaxyWorks"]
        assert gw["project_count"] == 10
        assert "cross_solution_ratio" in gw

        # Cluster alignment
        assert len(data["clusters"]) >= 1
        clu = data["clusters"][0]
        assert "solution_alignment" in clu
        assert "dominant_solution" in clu

        # Node solutions in topology
        assert "graph" in data
        gw_data = data["graph"]["nodes"].get("GalaxyWorks.Data")
        assert gw_data is not None
        assert "GalaxyWorks" in gw_data["solutions"]

        # Per-project solutions in metrics
        assert "GalaxyWorks" in data["metrics"]["GalaxyWorks.Data"]["solutions"]

    def test_csv_has_solutions_column(self, tmp_path):
        out = tmp_path / "graph.csv"
        rc, _, _ = _run_scatter(
            "--graph", "--include-db", "--search-scope", ".",
            "--rebuild-graph",
            "--output-format", "csv", "--output-file", str(out),
        )
        assert rc == 0
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert "Solutions" in reader.fieldnames
        gw_row = next(r for r in rows if r["Project"] == "GalaxyWorks.Data")
        assert "GalaxyWorks" in gw_row["Solutions"]


class TestTargetModeSolutions:
    def test_consuming_solutions_populated(self, tmp_path):
        out = tmp_path / "consumers.json"
        rc, _, _ = _run_scatter(
            "--target-project", "./GalaxyWorks.Data/GalaxyWorks.Data.csproj",
            "--search-scope", ".",
            "--output-format", "json", "--output-file", str(out),
        )
        assert rc == 0
        data = json.loads(out.read_text())
        results = data["all_results"]
        assert len(results) > 0
        # At least one consumer should have ConsumingSolutions populated
        solutions = [r.get("ConsumingSolutions", []) for r in results]
        assert any(s for s in solutions), "No ConsumingSolutions found in output"


class TestBackwardCompat:
    def test_no_sln_no_crash(self, tmp_path):
        """Directory with .csproj but no .sln files — no crash, no solution sections."""
        # Create minimal .csproj
        proj_dir = tmp_path / "TestProj"
        proj_dir.mkdir()
        (proj_dir / "TestProj.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>'
        )
        (proj_dir / "Class1.cs").write_text("namespace TestProj { class Class1 {} }")

        rc, stdout, _ = _run_scatter(
            "--graph", "--search-scope", str(tmp_path),
        )
        assert rc == 0
        assert "Solutions:" not in stdout
        assert "Solution Coupling" not in stdout
        assert "Align" not in stdout

    def test_no_graph_flag_works(self):
        """--no-graph skips graph loading, solutions still discovered."""
        rc, stdout, _ = _run_scatter(
            "--target-project", "./GalaxyWorks.Data/GalaxyWorks.Data.csproj",
            "--search-scope", ".", "--no-graph",
        )
        assert rc == 0
        assert "consumer" in stdout.lower() or "Consumer" in stdout
