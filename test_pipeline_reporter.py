"""Tests for scatter.reports.pipeline_reporter."""
import subprocess
import sys
from pathlib import Path

from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    ImpactReport,
    TargetImpact,
)
from scatter.reports.pipeline_reporter import (
    extract_impact_pipeline_names,
    extract_pipeline_names,
    format_pipeline_output,
    write_pipeline_report,
)


# ---------------------------------------------------------------------------
# extract_pipeline_names (legacy dicts)
# ---------------------------------------------------------------------------

class TestExtractPipelineNames:
    def test_extracts_unique_sorted(self):
        results = [
            {'PipelineName': 'deploy-api'},
            {'PipelineName': 'deploy-web'},
            {'PipelineName': 'deploy-api'},
        ]
        assert extract_pipeline_names(results) == ['deploy-api', 'deploy-web']

    def test_empty_results(self):
        assert extract_pipeline_names([]) == []

    def test_no_pipeline_field(self):
        results = [{'ConsumerProjectName': 'foo'}]
        assert extract_pipeline_names(results) == []

    def test_skips_none_values(self):
        results = [
            {'PipelineName': None},
            {'PipelineName': ''},
            {'PipelineName': 'deploy-api'},
        ]
        assert extract_pipeline_names(results) == ['deploy-api']


# ---------------------------------------------------------------------------
# extract_impact_pipeline_names
# ---------------------------------------------------------------------------

def _make_consumer(pipeline_name: str = "") -> EnrichedConsumer:
    return EnrichedConsumer(
        consumer_path=Path("/fake"),
        consumer_name="fake",
        pipeline_name=pipeline_name,
    )


def _make_target(*consumers: EnrichedConsumer) -> TargetImpact:
    return TargetImpact(
        target=AnalysisTarget(target_type="project", name="T"),
        consumers=list(consumers),
    )


class TestExtractImpactPipelineNames:
    def test_extracts_from_consumers(self):
        report = ImpactReport(
            sow_text="test",
            targets=[
                _make_target(_make_consumer("deploy-web"), _make_consumer("deploy-api")),
                _make_target(_make_consumer("deploy-web"), _make_consumer("deploy-batch")),
            ],
        )
        assert extract_impact_pipeline_names(report) == [
            'deploy-api', 'deploy-batch', 'deploy-web',
        ]

    def test_empty_pipeline_name(self):
        report = ImpactReport(
            sow_text="test",
            targets=[_make_target(_make_consumer(""), _make_consumer(""))],
        )
        assert extract_impact_pipeline_names(report) == []

    def test_no_consumers(self):
        report = ImpactReport(sow_text="test", targets=[])
        assert extract_impact_pipeline_names(report) == []


# ---------------------------------------------------------------------------
# format_pipeline_output
# ---------------------------------------------------------------------------

class TestFormatPipelineOutput:
    def test_one_per_line(self):
        assert format_pipeline_output(['a', 'b', 'c']) == 'a\nb\nc'

    def test_empty_list(self):
        assert format_pipeline_output([]) == ''

    def test_single(self):
        assert format_pipeline_output(['deploy-api']) == 'deploy-api'


# ---------------------------------------------------------------------------
# write_pipeline_report
# ---------------------------------------------------------------------------

class TestWritePipelineReport:
    def test_writes_file(self, tmp_path):
        out = tmp_path / "pipelines.txt"
        write_pipeline_report(['deploy-api', 'deploy-web'], out)
        assert out.read_text(encoding='utf-8') == 'deploy-api\ndeploy-web\n'

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "nested" / "deep" / "pipelines.txt"
        write_pipeline_report(['deploy-api'], out)
        assert out.exists()
        assert out.read_text(encoding='utf-8') == 'deploy-api\n'

    def test_empty_list_writes_empty_file(self, tmp_path):
        out = tmp_path / "pipelines.txt"
        write_pipeline_report([], out)
        assert out.read_text(encoding='utf-8') == ''


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestPipelinesCLI:
    def test_graph_mode_rejects_pipelines_format(self):
        result = subprocess.run(
            [sys.executable, "-m", "scatter", "--graph", "--search-scope", ".",
             "--output-format", "pipelines"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        assert "not supported in graph mode" in result.stderr
