"""Shared test fixtures for Scatter CLI tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.analyzers.coupling_analyzer import ProjectMetrics
from scatter.analysis import ModeContext
from scatter.core.models import ConsumerResult


def make_metrics(
    fan_in: int = 0,
    fan_out: int = 0,
    instability: float = 0.0,
    coupling_score: float = 0.0,
    shared_db_density: float = 0.0,
) -> ProjectMetrics:
    """Build a ProjectMetrics with sensible defaults for risk engine tests."""
    return ProjectMetrics(
        fan_in=fan_in,
        fan_out=fan_out,
        instability=instability,
        coupling_score=coupling_score,
        afferent_coupling=fan_in,
        efferent_coupling=fan_out,
        shared_db_density=shared_db_density,
        type_export_count=0,
        consumer_count=fan_in,
    )


@pytest.fixture
def make_mode_context():
    """Factory fixture for building ModeContext with sensible test defaults.

    Usage::

        def test_something(make_mode_context):
            ctx = make_mode_context(class_name="Foo")
    """

    def _factory(**overrides) -> ModeContext:
        defaults = dict(
            search_scope=Path("/tmp/scope"),
            config=MagicMock(),
            pipeline_map={},
            solution_file_cache=[],
            batch_job_map={},
            ai_provider=None,
            graph_ctx=None,
            solution_index=None,
            graph_enriched=False,
            class_name=None,
            method_name=None,
            target_namespace=None,
            summarize_consumers=False,
            max_workers=1,
            chunk_size=75,
            disable_multiprocessing=True,
            cs_analysis_chunk_size=50,
            csproj_analysis_chunk_size=25,
            no_graph=True,
        )
        defaults.update(overrides)
        return ModeContext(**defaults)

    return _factory


@pytest.fixture
def make_consumer_result():
    """Factory fixture for building ConsumerResult with sensible test defaults.

    Usage::

        def test_something(make_consumer_result):
            r = make_consumer_result(consumer_project_name="MyApp")
    """

    def _factory(**overrides) -> ConsumerResult:
        defaults = dict(
            target_project_name="TargetProject",
            target_project_path="TargetProject/TargetProject.csproj",
            triggering_type="SomeClass",
            consumer_project_name="ConsumerProject",
            consumer_project_path="ConsumerProject/ConsumerProject.csproj",
        )
        defaults.update(overrides)
        return ConsumerResult(**defaults)

    return _factory
