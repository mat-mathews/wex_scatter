"""Tests for _summarize_consumer_files wiring in __main__.py."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.__main__ import _summarize_consumer_files
from scatter.ai.base import AITaskType, AnalysisResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_consumer(name: str, files: list[Path], base: Path = Path('/repo')) -> dict:
    return {
        'consumer_name': name,
        'consumer_path': base / name / f'{name}.csproj',
        'relevant_files': files,
    }


def _make_result(consumer_name: str, consumer_path: Path = None,
                 search_scope: Path = Path('/repo')) -> dict:
    if consumer_path is None:
        consumer_path = search_scope / consumer_name / f'{consumer_name}.csproj'
    try:
        rel = consumer_path.relative_to(search_scope).as_posix()
    except ValueError:
        rel = consumer_path.as_posix()
    return {
        'TargetProjectName': 'Target',
        'ConsumerProjectName': consumer_name,
        'ConsumerProjectPath': rel,
        'ConsumerFileSummaries': {},
    }


def _mock_provider(supports=True, response="This file does X."):
    provider = MagicMock()
    provider.supports.return_value = supports
    provider.analyze.return_value = AnalysisResult(response=response)
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSummarizeConsumerFiles:
    """Tests for the _summarize_consumer_files helper."""

    def test_happy_path(self, tmp_path):
        """Summaries are generated and injected into result dicts."""
        cs_file = tmp_path / "Service.cs"
        cs_file.write_text("public class Service { }")

        consumers = [_make_consumer("ConsumerA", [cs_file], base=tmp_path)]
        results = [_make_result("ConsumerA", search_scope=tmp_path)]
        provider = _mock_provider(response="Service handles business logic.")

        _summarize_consumer_files(consumers, results, provider, tmp_path, 0)

        summaries = results[0]['ConsumerFileSummaries']
        assert len(summaries) == 1
        assert summaries["Service.cs"] == "Service handles business logic."
        provider.analyze.assert_called_once()
        assert provider.analyze.call_args[0][2] == AITaskType.SUMMARIZATION

    def test_no_provider_is_noop(self):
        """When ai_provider is None, nothing happens."""
        consumers = [_make_consumer("A", [Path("/fake.cs")])]
        results = [_make_result("A")]

        _summarize_consumer_files(consumers, results, None, Path("/repo"), 0)

        assert results[0]['ConsumerFileSummaries'] == {}

    def test_unsupported_task_type(self, tmp_path):
        """When provider doesn't support SUMMARIZATION, skip gracefully."""
        cs_file = tmp_path / "Foo.cs"
        cs_file.write_text("class Foo {}")

        consumers = [_make_consumer("A", [cs_file], base=tmp_path)]
        results = [_make_result("A", search_scope=tmp_path)]
        provider = _mock_provider(supports=False)

        _summarize_consumer_files(consumers, results, provider, tmp_path, 0)

        assert results[0]['ConsumerFileSummaries'] == {}
        provider.analyze.assert_not_called()

    def test_partial_failure(self, tmp_path):
        """If one file fails, others still get summarized."""
        good_file = tmp_path / "Good.cs"
        good_file.write_text("class Good {}")
        bad_file = tmp_path / "Bad.cs"
        bad_file.write_text("class Bad {}")

        consumers = [_make_consumer("A", [good_file, bad_file], base=tmp_path)]
        results = [_make_result("A", search_scope=tmp_path)]

        provider = MagicMock()
        provider.supports.return_value = True
        provider.analyze.side_effect = [
            AnalysisResult(response="Good does things."),
            Exception("API timeout"),
        ]

        _summarize_consumer_files(consumers, results, provider, tmp_path, 0)

        summaries = results[0]['ConsumerFileSummaries']
        assert len(summaries) == 1
        assert summaries["Good.cs"] == "Good does things."

    def test_no_relevant_files(self):
        """Consumers with empty relevant_files produce no summaries."""
        consumers = [_make_consumer("A", [])]
        results = [_make_result("A")]
        provider = _mock_provider()

        _summarize_consumer_files(consumers, results, provider, Path("/repo"), 0)

        assert results[0]['ConsumerFileSummaries'] == {}
        provider.analyze.assert_not_called()

    def test_results_start_index(self, tmp_path):
        """Only result dicts from results_start_index onward are enriched."""
        cs_file = tmp_path / "Svc.cs"
        cs_file.write_text("class Svc {}")

        consumers = [_make_consumer("B", [cs_file], base=tmp_path)]
        results = [_make_result("OldConsumer", search_scope=tmp_path),
                   _make_result("B", search_scope=tmp_path)]
        provider = _mock_provider(response="Svc summary.")

        _summarize_consumer_files(consumers, results, provider, tmp_path, 1)

        assert results[0]['ConsumerFileSummaries'] == {}
        assert len(results[1]['ConsumerFileSummaries']) == 1

    def test_same_stem_different_paths(self, tmp_path):
        """Two consumers with the same name but different paths get independent summaries."""
        dir_a = tmp_path / "src" / "Worker"
        dir_b = tmp_path / "lib" / "Worker"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        file_a = tmp_path / "A.cs"
        file_a.write_text("class A {}")
        file_b = tmp_path / "B.cs"
        file_b.write_text("class B {}")

        path_a = dir_a / "Worker.csproj"
        path_b = dir_b / "Worker.csproj"

        consumers = [
            {'consumer_name': 'Worker', 'consumer_path': path_a, 'relevant_files': [file_a]},
            {'consumer_name': 'Worker', 'consumer_path': path_b, 'relevant_files': [file_b]},
        ]

        rel_a = path_a.relative_to(tmp_path).as_posix()
        rel_b = path_b.relative_to(tmp_path).as_posix()
        results = [
            {'TargetProjectName': 'T', 'ConsumerProjectName': 'Worker',
             'ConsumerProjectPath': rel_a, 'ConsumerFileSummaries': {}},
            {'TargetProjectName': 'T', 'ConsumerProjectName': 'Worker',
             'ConsumerProjectPath': rel_b, 'ConsumerFileSummaries': {}},
        ]

        provider = MagicMock()
        provider.supports.return_value = True
        provider.analyze.side_effect = [
            AnalysisResult(response="A summary"),
            AnalysisResult(response="B summary"),
        ]

        _summarize_consumer_files(consumers, results, provider, tmp_path, 0)

        assert results[0]['ConsumerFileSummaries']["A.cs"] == "A summary"
        assert results[1]['ConsumerFileSummaries']["B.cs"] == "B summary"
