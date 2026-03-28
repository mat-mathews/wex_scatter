#!/usr/bin/env python3
"""Tests for Initiative 6 Phase 2: Filter Pipeline Visibility."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scatter.core.models import (
    FilterStage, FilterPipeline,
    STAGE_DISCOVERY, STAGE_PROJECT_REFERENCE, STAGE_NAMESPACE, STAGE_CLASS,
)
from scatter.analyzers.consumer_analyzer import find_consumers
from scatter.reports.console_reporter import print_console_report, print_filter_pipeline
from scatter.reports.json_reporter import write_json_report
from scatter.reports.csv_reporter import write_csv_report


# ---------------------------------------------------------------------------
# Shared test fixture — single source of truth for synthetic pipelines.
# ---------------------------------------------------------------------------

def _make_pipeline(zero_class=False, include_class=True):
    """Build a representative FilterPipeline for reporter tests.

    Args:
        zero_class: If True, the class stage drops everything to 0.
        include_class: If False, omit the class stage entirely.
    """
    stages = [
        FilterStage(STAGE_DISCOVERY, 11, 10),
        FilterStage(STAGE_PROJECT_REFERENCE, 10, 4),
        FilterStage(STAGE_NAMESPACE, 4, 3),
    ]
    if include_class:
        stages.append(FilterStage(STAGE_CLASS, 3, 0 if zero_class else 2))
    return FilterPipeline(
        search_scope="/path/to/repo",
        total_projects_scanned=11,
        total_files_scanned=47,
        stages=stages,
        target_project="GalaxyWorks.Data",
        target_namespace="GalaxyWorks.Data",
        class_filter="PortalDataService",
    )


def _make_large_pipeline():
    """Build a larger pipeline for JSON/CSV tests."""
    return FilterPipeline(
        search_scope="/path/to/repo",
        total_projects_scanned=200,
        total_files_scanned=1847,
        stages=[
            FilterStage(STAGE_DISCOVERY, 201, 200),
            FilterStage(STAGE_PROJECT_REFERENCE, 200, 12),
            FilterStage(STAGE_NAMESPACE, 12, 8),
            FilterStage(STAGE_CLASS, 8, 4),
        ],
        target_project="GalaxyWorks.Data",
        target_namespace="GalaxyWorks.Data",
        class_filter="PortalDataService",
    )


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------

class TestFilterPipelineDataModel(unittest.TestCase):
    """Test FilterStage and FilterPipeline dataclass construction."""

    def test_filter_stage_construction(self):
        """FilterStage fields are set correctly."""
        stage = FilterStage(name=STAGE_DISCOVERY, input_count=200, output_count=199)
        self.assertEqual(stage.name, STAGE_DISCOVERY)
        self.assertEqual(stage.input_count, 200)
        self.assertEqual(stage.output_count, 199)

    def test_filter_stage_dropped_count(self):
        """dropped_count property returns input - output."""
        stage = FilterStage(name=STAGE_PROJECT_REFERENCE, input_count=200, output_count=12)
        self.assertEqual(stage.dropped_count, 188)

    def test_filter_pipeline_construction(self):
        """FilterPipeline with stages, search_scope, counts."""
        pipeline = _make_pipeline()
        self.assertEqual(pipeline.search_scope, "/path/to/repo")
        self.assertEqual(pipeline.total_projects_scanned, 11)
        self.assertEqual(pipeline.total_files_scanned, 47)
        self.assertEqual(len(pipeline.stages), 4)
        self.assertEqual(pipeline.target_project, "GalaxyWorks.Data")
        self.assertEqual(pipeline.class_filter, "PortalDataService")
        self.assertIsNone(pipeline.method_filter)

    def test_filter_pipeline_empty_stages(self):
        """Empty stages list is valid."""
        pipeline = FilterPipeline(
            search_scope="/tmp",
            total_projects_scanned=0,
            total_files_scanned=0,
        )
        self.assertEqual(pipeline.stages, [])
        self.assertEqual(pipeline.target_project, "")
        self.assertEqual(pipeline.target_namespace, "")

    def test_format_arrow_chain(self):
        """format_arrow_chain produces arrow-separated string."""
        pipeline = _make_pipeline()
        chain = pipeline.format_arrow_chain()
        self.assertIn("\u2192", chain)
        self.assertIn("project refs", chain)
        self.assertIn("class match", chain)

    def test_filter_value_for_stage(self):
        """filter_value_for_stage returns correct filter values."""
        pipeline = _make_pipeline()
        self.assertEqual(pipeline.filter_value_for_stage(STAGE_CLASS), "PortalDataService")
        self.assertEqual(pipeline.filter_value_for_stage(STAGE_NAMESPACE), "GalaxyWorks.Data")
        self.assertIsNone(pipeline.filter_value_for_stage("nonexistent"))


# ---------------------------------------------------------------------------
# Integration tests — find_consumers returns pipeline
# ---------------------------------------------------------------------------

class TestFindConsumersReturnsPipeline(unittest.TestCase):
    """Test that find_consumers returns a (results, FilterPipeline) tuple."""

    def setUp(self):
        self.test_root = Path(__file__).parent.parent.parent.resolve()
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        self.exclude_project = self.test_root / "MyDotNetApp2.Exclude" / "MyDotNetApp2.Exclude.csproj"

    def test_target_mode_returns_pipeline(self):
        """find_consumers returns a tuple with a FilterPipeline."""
        result = find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        consumers, pipeline = result
        self.assertIsInstance(consumers, list)
        self.assertIsInstance(pipeline, FilterPipeline)
        self.assertGreater(len(pipeline.stages), 0)

    def test_pipeline_discovery_stage(self):
        """Discovery stage shows correct total .csproj count."""
        consumers, pipeline = find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        discovery = pipeline.stages[0]
        self.assertEqual(discovery.name, STAGE_DISCOVERY)
        self.assertEqual(discovery.input_count, pipeline.total_projects_scanned)
        # Output should be one less than input (target excluded)
        self.assertEqual(discovery.output_count, discovery.input_count - 1)

    def test_pipeline_project_ref_stage(self):
        """project_reference stage output matches known consumer count."""
        consumers, pipeline = find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        # Should have at least discovery and project_reference stages
        self.assertGreaterEqual(len(pipeline.stages), 2)
        proj_ref = pipeline.stages[1]
        self.assertEqual(proj_ref.name, STAGE_PROJECT_REFERENCE)
        self.assertGreater(proj_ref.output_count, 0)

    def test_pipeline_with_class_filter(self):
        """Class filter stage appears when class_name is provided."""
        consumers, pipeline = find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalDataService",
            method_name=None,
            disable_multiprocessing=True,
        )
        stage_names = [s.name for s in pipeline.stages]
        self.assertIn(STAGE_CLASS, stage_names)
        self.assertEqual(pipeline.class_filter, "PortalDataService")

    def test_pipeline_zero_results(self):
        """Pipeline is still populated when no consumers found."""
        consumers, pipeline = find_consumers(
            target_csproj_path=self.exclude_project,
            search_scope_path=self.test_root,
            target_namespace="MyDotNetApp2.Exclude",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
        )
        self.assertEqual(len(consumers), 0)
        self.assertIsInstance(pipeline, FilterPipeline)
        self.assertGreater(len(pipeline.stages), 0)
        self.assertEqual(pipeline.target_project, "MyDotNetApp2.Exclude")


# ---------------------------------------------------------------------------
# Console reporter tests
# ---------------------------------------------------------------------------

class TestConsoleFilterOutput(unittest.TestCase):
    """Test console reporter filter pipeline output."""

    def test_filter_line_in_console_output(self):
        """Captured stdout contains 'Filter:' line with arrow notation."""
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            print_filter_pipeline(_make_pipeline())
        output = captured.getvalue()
        self.assertIn("Filter:", output)
        self.assertIn("\u2192", output)

    def test_search_scope_line(self):
        """'Search scope:' line present with project and file counts."""
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            print_filter_pipeline(_make_pipeline())
        output = captured.getvalue()
        self.assertIn("Search scope:", output)
        self.assertIn("11 projects", output)
        self.assertIn("47 files", output)

    def test_zero_results_hint(self):
        """Zero results at a stage produces 'Hint:' line."""
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            print_filter_pipeline(_make_pipeline(zero_class=True))
        output = captured.getvalue()
        self.assertIn("Hint:", output)
        self.assertIn("PortalDataService", output)

    def test_no_pipeline_no_crash(self):
        """print_console_report(results, pipeline=None) works (backward compat)."""
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            print_console_report([], pipeline=None)
        output = captured.getvalue()
        self.assertIn("No consuming relationships found.", output)
        self.assertNotIn("Search scope:", output)


# ---------------------------------------------------------------------------
# JSON reporter tests
# ---------------------------------------------------------------------------

class TestJsonFilterPipeline(unittest.TestCase):
    """Test JSON reporter filter pipeline output."""

    def test_json_includes_filter_pipeline(self):
        """'filter_pipeline' key appears in JSON output."""
        pipeline = _make_large_pipeline()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            write_json_report([], tmp_path, pipeline=pipeline)
            data = json.loads(tmp_path.read_text())
            self.assertIn("filter_pipeline", data)
            self.assertEqual(data["filter_pipeline"]["search_scope"], "/path/to/repo")
            self.assertEqual(data["filter_pipeline"]["total_projects_scanned"], 200)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_json_pipeline_stages_array(self):
        """stages is a list of dicts with name/input_count/output_count."""
        pipeline = _make_large_pipeline()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            write_json_report([], tmp_path, pipeline=pipeline)
            data = json.loads(tmp_path.read_text())
            stages = data["filter_pipeline"]["stages"]
            self.assertIsInstance(stages, list)
            self.assertEqual(len(stages), 4)
            for stage in stages:
                self.assertIn("name", stage)
                self.assertIn("input_count", stage)
                self.assertIn("output_count", stage)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_json_no_pipeline_backward_compat(self):
        """Omitting pipeline param produces output without 'filter_pipeline' key."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            write_json_report([], tmp_path)
            data = json.loads(tmp_path.read_text())
            self.assertNotIn("filter_pipeline", data)
            self.assertIn("pipeline_summary", data)
            self.assertIn("all_results", data)
        finally:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CSV reporter tests
# ---------------------------------------------------------------------------

class TestCsvFilterPipeline(unittest.TestCase):
    """Test CSV reporter filter pipeline output."""

    def test_csv_comment_header(self):
        """First line(s) of CSV start with #."""
        pipeline = _make_large_pipeline()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            write_csv_report([], tmp_path, pipeline=pipeline)
            content = tmp_path.read_text()
            first_line = content.split("\n")[0]
            self.assertTrue(first_line.startswith("#"))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_filter_summary_in_header(self):
        """Filter arrow notation appears in comment header."""
        pipeline = _make_large_pipeline()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            write_csv_report([], tmp_path, pipeline=pipeline)
            content = tmp_path.read_text()
            comment_lines = [l for l in content.split("\n") if l.startswith("#")]
            comment_text = "\n".join(comment_lines)
            self.assertIn("\u2192", comment_text)
            self.assertIn("project refs", comment_text)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_no_pipeline_no_header(self):
        """Omitting pipeline produces clean CSV (no comment header)."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            write_csv_report([], tmp_path)
            content = tmp_path.read_text()
            first_line = content.split("\n")[0]
            self.assertFalse(first_line.startswith("#"))
            self.assertIn("TargetProjectName", first_line)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
