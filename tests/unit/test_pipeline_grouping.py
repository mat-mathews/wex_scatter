"""Tests for pipeline grouping, dedup, and unified resolution."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.core.models import ConsumerResult, EnrichedConsumer, ImpactReport, TargetImpact
from scatter.reports.pipeline_reporter import (
    group_by_pipeline,
    group_impact_by_pipeline,
    extract_pipeline_names,
)


# ---------------------------------------------------------------------------
# Part 1: Unified pipeline resolution (v1_bridge fallback)
# ---------------------------------------------------------------------------


class TestV1BridgePipelineFallback:
    """Verify the consumer-name fallback in _build_consumer_results."""

    def _run_bridge(self, pipeline_map, solutions, consumer_name="Consumer"):
        from scatter.compat.v1_bridge import _build_consumer_results

        results = []
        _build_consumer_results(
            target_project_name="Target",
            target_project_rel_path_str="Target/Target.csproj",
            triggering_info="N/A",
            final_consumers_data=[
                {"consumer_path": Path(f"/repo/{consumer_name}/{consumer_name}.csproj"),
                 "consumer_name": consumer_name}
            ],
            all_results_list=results,
            pipeline_map_dict=pipeline_map,
            solution_file_cache=[],
            batch_job_map={},
            search_scope_path_abs=Path("/repo"),
            solution_index=MagicMock(
                get=lambda stem, default=None: solutions.get(stem, default)
            ),
        )
        return results

    def test_solution_stem_maps_to_pipeline(self):
        """Solution stem found in pipeline_map — standard path."""
        solutions = {"Consumer": [MagicMock(path=Path("/repo/App.sln"), name="App.sln", stem="App")]}
        results = self._run_bridge({"App": "deploy-app"}, solutions)
        assert len(results) == 1
        assert results[0].pipeline_name == "deploy-app"

    def test_consumer_name_fallback_when_solution_misses(self):
        """Solution exists but its stem isn't in pipeline_map — fallback to consumer name."""
        solutions = {"Consumer": [MagicMock(path=Path("/repo/Other.sln"), name="Other.sln", stem="Other")]}
        results = self._run_bridge({"Consumer": "deploy-consumer"}, solutions)
        assert len(results) == 1
        assert results[0].pipeline_name == "deploy-consumer"

    def test_consumer_name_fallback_no_solutions(self):
        """No solutions found at all — fallback to consumer name."""
        solutions = {}
        results = self._run_bridge({"Consumer": "deploy-consumer"}, solutions)
        assert len(results) == 1
        assert results[0].pipeline_name == "deploy-consumer"

    def test_no_match_anywhere(self):
        """Neither solution stem nor consumer name in pipeline_map."""
        solutions = {"Consumer": [MagicMock(path=Path("/repo/Other.sln"), name="Other.sln", stem="Other")]}
        results = self._run_bridge({"Unrelated": "deploy-x"}, solutions)
        assert len(results) == 1
        assert results[0].pipeline_name is None

    def test_solution_stem_wins_over_consumer_name(self):
        """Both solution stem and consumer name are in pipeline_map — solution wins."""
        solutions = {"Consumer": [MagicMock(path=Path("/repo/App.sln"), name="App.sln", stem="App")]}
        results = self._run_bridge(
            {"App": "deploy-via-solution", "Consumer": "deploy-via-name"},
            solutions,
        )
        assert len(results) == 1
        assert results[0].pipeline_name == "deploy-via-solution"


# ---------------------------------------------------------------------------
# Part 2: Pipeline grouping
# ---------------------------------------------------------------------------


def _make_result(consumer_name, pipeline_name=None):
    return ConsumerResult(
        target_project_name="Target",
        target_project_path="Target/Target.csproj",
        triggering_type="N/A",
        consumer_project_name=consumer_name,
        consumer_project_path=f"{consumer_name}/{consumer_name}.csproj",
        consuming_solutions=[],
        pipeline_name=pipeline_name,
    )


def _make_enriched(consumer_name, pipeline_name=""):
    return EnrichedConsumer(
        consumer_path=Path(f"/repo/{consumer_name}"),
        consumer_name=consumer_name,
        pipeline_name=pipeline_name,
    )


class TestGroupByPipeline:
    def test_groups_consumers_by_pipeline(self):
        results = [
            _make_result("Api", "deploy-api"),
            _make_result("Web", "deploy-api"),
            _make_result("Svc", "deploy-svc"),
        ]
        groups = group_by_pipeline(results)
        assert len(groups) == 2
        api_group = next(g for g in groups if g["pipeline_name"] == "deploy-api")
        assert api_group["consumer_count"] == 2
        assert sorted(api_group["consumers"]) == ["Api", "Web"]

    def test_omits_consumers_without_pipeline(self):
        results = [
            _make_result("Api", "deploy-api"),
            _make_result("Unmapped", None),
        ]
        groups = group_by_pipeline(results)
        assert len(groups) == 1
        assert groups[0]["pipeline_name"] == "deploy-api"

    def test_deduplicates_consumers(self):
        results = [
            _make_result("Api", "deploy-api"),
            _make_result("Api", "deploy-api"),
        ]
        groups = group_by_pipeline(results)
        assert groups[0]["consumer_count"] == 1

    def test_empty_results(self):
        assert group_by_pipeline([]) == []

    def test_all_unmapped(self):
        results = [_make_result("A", None), _make_result("B", None)]
        assert group_by_pipeline(results) == []

    def test_sorted_by_pipeline_name(self):
        results = [
            _make_result("Z", "zeta"),
            _make_result("A", "alpha"),
        ]
        groups = group_by_pipeline(results)
        assert groups[0]["pipeline_name"] == "alpha"
        assert groups[1]["pipeline_name"] == "zeta"


class TestGroupImpactByPipeline:
    def test_groups_across_targets(self):
        report = ImpactReport(
            sow_text="test",
            targets=[
                TargetImpact(
                    target=MagicMock(),
                    consumers=[
                        _make_enriched("Api", "deploy-api"),
                        _make_enriched("Web", "deploy-api"),
                    ],
                ),
                TargetImpact(
                    target=MagicMock(),
                    consumers=[
                        _make_enriched("Svc", "deploy-svc"),
                    ],
                ),
            ],
        )
        groups = group_impact_by_pipeline(report)
        assert len(groups) == 2

    def test_deduplicates_across_targets(self):
        """Same consumer in multiple targets shouldn't be double-counted."""
        report = ImpactReport(
            sow_text="test",
            targets=[
                TargetImpact(target=MagicMock(), consumers=[_make_enriched("Api", "deploy-api")]),
                TargetImpact(target=MagicMock(), consumers=[_make_enriched("Api", "deploy-api")]),
            ],
        )
        groups = group_impact_by_pipeline(report)
        assert groups[0]["consumer_count"] == 1

    def test_empty_pipeline_excluded(self):
        report = ImpactReport(
            sow_text="test",
            targets=[
                TargetImpact(target=MagicMock(), consumers=[_make_enriched("Api", "")]),
            ],
        )
        assert group_impact_by_pipeline(report) == []


# ---------------------------------------------------------------------------
# Part 2: JSON reporter pipeline_groups
# ---------------------------------------------------------------------------


class TestJsonPipelineGroups:
    def test_json_report_includes_pipeline_groups(self, tmp_path):
        from scatter.reports.json_reporter import write_json_report, REPORT_SCHEMA_VERSION

        detailed = [
            {"ConsumerProjectName": "Api", "PipelineName": "deploy-api"},
            {"ConsumerProjectName": "Web", "PipelineName": "deploy-api"},
            {"ConsumerProjectName": "Svc", "PipelineName": "deploy-svc"},
        ]
        out = tmp_path / "report.json"
        write_json_report(detailed, out)
        data = json.loads(out.read_text())

        assert "pipeline_groups" in data
        groups = data["pipeline_groups"]
        assert len(groups) == 2
        api_group = next(g for g in groups if g["pipeline_name"] == "deploy-api")
        assert api_group["consumer_count"] == 2
        assert sorted(api_group["consumers"]) == ["Api", "Web"]

    def test_json_report_omits_pipeline_groups_when_none(self, tmp_path):
        from scatter.reports.json_reporter import write_json_report

        detailed = [{"ConsumerProjectName": "Api", "PipelineName": None}]
        out = tmp_path / "report.json"
        write_json_report(detailed, out)
        data = json.loads(out.read_text())
        assert "pipeline_groups" not in data

    def test_schema_version_bumped(self):
        from scatter.reports.json_reporter import REPORT_SCHEMA_VERSION

        assert REPORT_SCHEMA_VERSION == "1.1"


# ---------------------------------------------------------------------------
# Part 2: Console reporter grouped output
# ---------------------------------------------------------------------------


class TestConsoleGroupedOutput:
    def test_console_shows_grouped_pipelines(self, capsys):
        from scatter.reports.console_reporter import print_console_report

        results = [
            _make_result("Api", "deploy-api"),
            _make_result("Web", "deploy-api"),
            _make_result("Svc", "deploy-svc"),
        ]
        print_console_report(results)
        output = capsys.readouterr().out

        assert "Pipelines affected: 2" in output
        assert "deploy-api (2 project(s))" in output
        assert "deploy-svc (1 project(s))" in output
        assert "• Api" in output
        assert "• Web" in output

    def test_console_omits_pipeline_section_when_none(self, capsys):
        from scatter.reports.console_reporter import print_console_report

        results = [_make_result("Api", None)]
        print_console_report(results)
        output = capsys.readouterr().out
        assert "Pipelines affected" not in output
