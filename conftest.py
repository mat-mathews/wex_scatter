"""Shared test fixtures for Scatter CLI tests."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.cli import ModeContext


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
