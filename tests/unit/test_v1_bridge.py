"""Tests for scatter.compat.v1_bridge — pipeline mapping, solution lookup, result processing."""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.compat.v1_bridge import (
    find_solutions_for_project,
    map_batch_jobs_from_config_repo,
    _process_consumer_summaries_and_append_results,
)
from scatter.core.models import ConsumerResult


# ---------------------------------------------------------------------------
# find_solutions_for_project
# ---------------------------------------------------------------------------


class TestFindSolutionsForProject:
    def test_uses_solution_index_when_provided(self):
        si = MagicMock()
        si.path = Path("/repo/Foo.sln")
        index = {"Foo": [si]}

        result = find_solutions_for_project(
            Path("/repo/Foo/Foo.csproj"), solution_cache=[], solution_index=index
        )
        assert result == [Path("/repo/Foo.sln")]

    def test_index_miss_returns_empty(self):
        result = find_solutions_for_project(
            Path("/repo/Foo/Foo.csproj"), solution_cache=[], solution_index={}
        )
        assert result == []

    def test_legacy_text_search(self, tmp_path):
        sln = tmp_path / "MySolution.sln"
        sln.write_text('Project("...") = "Foo", "Foo\\Foo.csproj"')

        result = find_solutions_for_project(
            Path("/repo/Foo/Foo.csproj"), solution_cache=[sln], solution_index=None
        )
        assert result == [sln]

    def test_legacy_no_match(self, tmp_path):
        sln = tmp_path / "Other.sln"
        sln.write_text('Project("...") = "Bar", "Bar\\Bar.csproj"')

        result = find_solutions_for_project(
            Path("/repo/Foo/Foo.csproj"), solution_cache=[sln], solution_index=None
        )
        assert result == []

    def test_empty_cache_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = find_solutions_for_project(
                Path("/repo/Foo/Foo.csproj"), solution_cache=[], solution_index=None
            )
        assert result == []
        assert "empty" in caplog.text.lower()

    def test_handles_unreadable_solution(self, tmp_path):
        sln = tmp_path / "Bad.sln"
        sln.write_text("content")
        # Make unreadable
        sln.chmod(0o000)
        try:
            result = find_solutions_for_project(
                Path("/repo/Foo/Foo.csproj"), solution_cache=[sln], solution_index=None
            )
            assert result == []
        finally:
            sln.chmod(0o644)


# ---------------------------------------------------------------------------
# map_batch_jobs_from_config_repo
# ---------------------------------------------------------------------------


class TestMapBatchJobsFromConfigRepo:
    def test_returns_empty_for_none_path(self):
        assert map_batch_jobs_from_config_repo(None) == {}

    def test_returns_empty_for_nonexistent_path(self):
        assert map_batch_jobs_from_config_repo(Path("/no/such/path")) == {}

    def test_returns_empty_when_no_production_dir(self, tmp_path):
        result = map_batch_jobs_from_config_repo(tmp_path)
        assert result == {}

    def test_finds_batch_jobs(self, tmp_path):
        prod_dir = tmp_path / "cdh-batchprocesses-az-cd" / "production"
        prod_dir.mkdir(parents=True)
        (prod_dir / "job-alpha").mkdir()
        (prod_dir / "job-beta").mkdir()

        result = map_batch_jobs_from_config_repo(tmp_path)
        assert "cdh-batchprocesses-az-cd" in result
        assert sorted(result["cdh-batchprocesses-az-cd"]) == ["job-alpha", "job-beta"]

    def test_empty_production_dir(self, tmp_path):
        prod_dir = tmp_path / "cdh-batchprocesses-az-cd" / "production"
        prod_dir.mkdir(parents=True)

        result = map_batch_jobs_from_config_repo(tmp_path)
        assert result == {}


# ---------------------------------------------------------------------------
# _process_consumer_summaries_and_append_results
# ---------------------------------------------------------------------------


class TestProcessConsumerSummaries:
    def test_empty_consumers_logs_and_returns(self, caplog):
        results = []
        with caplog.at_level(logging.INFO):
            _process_consumer_summaries_and_append_results(
                target_project_name="Foo",
                target_project_rel_path_str="Foo/Foo.csproj",
                triggering_info="SomeClass",
                final_consumers_data=[],
                all_results_list=results,
                pipeline_map_dict={},
                solution_file_cache=[],
                batch_job_map={},
                search_scope_path_abs=Path("/repo"),
            )
        assert results == []
        assert "no consumers" in caplog.text.lower()

    def test_appends_result_without_pipeline(self):
        consumer = {
            "consumer_name": "Bar",
            "consumer_path": Path("/repo/Bar/Bar.csproj"),
            "relevant_files": [],
        }
        results = []
        _process_consumer_summaries_and_append_results(
            target_project_name="Foo",
            target_project_rel_path_str="Foo/Foo.csproj",
            triggering_info="SomeClass",
            final_consumers_data=[consumer],
            all_results_list=results,
            pipeline_map_dict={},
            solution_file_cache=[],
            batch_job_map={},
            search_scope_path_abs=Path("/repo"),
        )
        assert len(results) == 1
        assert results[0].consumer_project_name == "Bar"
        assert results[0].pipeline_name is None

    def test_appends_result_with_pipeline_via_solution_index(self):
        consumer = {
            "consumer_name": "Bar",
            "consumer_path": Path("/repo/Bar/Bar.csproj"),
            "relevant_files": [],
        }
        si = MagicMock()
        si.path = Path("/repo/BarSln.sln")
        solution_index = {"Bar": [si]}

        results = []
        _process_consumer_summaries_and_append_results(
            target_project_name="Foo",
            target_project_rel_path_str="Foo/Foo.csproj",
            triggering_info="SomeClass",
            final_consumers_data=[consumer],
            all_results_list=results,
            pipeline_map_dict={"BarSln": "pipeline-bar"},
            solution_file_cache=[],
            batch_job_map={},
            search_scope_path_abs=Path("/repo"),
            solution_index=solution_index,
        )
        assert len(results) == 1
        assert results[0].pipeline_name == "pipeline-bar"

    def test_batch_job_verified(self):
        consumer = {
            "consumer_name": "job-alpha",
            "consumer_path": Path("/repo/job-alpha/job-alpha.csproj"),
            "relevant_files": [],
        }
        si = MagicMock()
        si.path = Path("/repo/BatchSln.sln")
        solution_index = {"job-alpha": [si]}

        results = []
        _process_consumer_summaries_and_append_results(
            target_project_name="Foo",
            target_project_rel_path_str="Foo/Foo.csproj",
            triggering_info="SomeClass",
            final_consumers_data=[consumer],
            all_results_list=results,
            pipeline_map_dict={"BatchSln": "cdh-batchprocesses-az-cd"},
            solution_file_cache=[],
            batch_job_map={"cdh-batchprocesses-az-cd": ["job-alpha", "job-beta"]},
            search_scope_path_abs=Path("/repo"),
            solution_index=solution_index,
        )
        assert len(results) == 1
        assert results[0].batch_job_verification == "Verified"

    def test_batch_job_unverified(self):
        consumer = {
            "consumer_name": "job-unknown",
            "consumer_path": Path("/repo/job-unknown/job-unknown.csproj"),
            "relevant_files": [],
        }
        si = MagicMock()
        si.path = Path("/repo/BatchSln.sln")
        solution_index = {"job-unknown": [si]}

        results = []
        _process_consumer_summaries_and_append_results(
            target_project_name="Foo",
            target_project_rel_path_str="Foo/Foo.csproj",
            triggering_info="SomeClass",
            final_consumers_data=[consumer],
            all_results_list=results,
            pipeline_map_dict={"BatchSln": "cdh-batchprocesses-az-cd"},
            solution_file_cache=[],
            batch_job_map={"cdh-batchprocesses-az-cd": ["job-alpha"]},
            search_scope_path_abs=Path("/repo"),
            solution_index=solution_index,
        )
        assert len(results) == 1
        assert results[0].batch_job_verification == "Unverified"

    def test_consumer_relative_path(self):
        consumer = {
            "consumer_name": "Bar",
            "consumer_path": Path("/repo/sub/Bar/Bar.csproj"),
            "relevant_files": [],
        }
        results = []
        _process_consumer_summaries_and_append_results(
            target_project_name="Foo",
            target_project_rel_path_str="Foo/Foo.csproj",
            triggering_info="SomeClass",
            final_consumers_data=[consumer],
            all_results_list=results,
            pipeline_map_dict={},
            solution_file_cache=[],
            batch_job_map={},
            search_scope_path_abs=Path("/repo"),
        )
        assert results[0].consumer_project_path == "sub/Bar/Bar.csproj"
