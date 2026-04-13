"""Regression test: hybrid consumer analysis must produce <= results than regex.

Runs find_consumers() on sample projects in both regex and hybrid modes,
then asserts that hybrid results are a subset of regex results.
"""

from pathlib import Path

import pytest

from scatter.config import AnalysisConfig

# Sample projects live in samples/
SEARCH_SCOPE = Path(__file__).resolve().parents[2] / "samples"


def _find_consumers_for_mode(parser_mode: str):
    """Run find_consumers in target mode for GalaxyWorks.Data with the given parser mode."""
    from scatter.analyzers.consumer_analyzer import find_consumers
    from scatter.scanners.project_scanner import derive_namespace

    target = SEARCH_SCOPE / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
    if not target.exists():
        pytest.skip("Sample project GalaxyWorks.Data not found")

    namespace = derive_namespace(target) or "GalaxyWorks.Data"
    config = AnalysisConfig(parser_mode=parser_mode)

    consumers, pipeline = find_consumers(
        target_csproj_path=target,
        search_scope_path=SEARCH_SCOPE,
        target_namespace=namespace,
        class_name="PortalDataService",
        method_name=None,
        disable_multiprocessing=True,
        analysis_config=config,
    )
    return consumers, pipeline


@pytest.mark.integration
class TestHybridConsumerRegression:
    @pytest.fixture(scope="class")
    def regex_results(self):
        return _find_consumers_for_mode("regex")

    @pytest.fixture(scope="class")
    def hybrid_results(self):
        return _find_consumers_for_mode("hybrid")

    def test_hybrid_consumer_count_lte_regex(self, regex_results, hybrid_results):
        """Hybrid mode should produce the same or fewer consumers."""
        regex_consumers, _ = regex_results
        hybrid_consumers, _ = hybrid_results
        regex_names = {c["consumer_name"] for c in regex_consumers}
        hybrid_names = {c["consumer_name"] for c in hybrid_consumers}
        delta = regex_names - hybrid_names
        if delta:
            print(f"\n  Consumers eliminated by hybrid: {delta}")
        print(
            f"\n  Consumer count — regex: {len(regex_names)}, "
            f"hybrid: {len(hybrid_names)}, delta: {len(delta)}"
        )
        assert hybrid_names <= regex_names

    def test_both_modes_return_filter_pipeline(self, regex_results, hybrid_results):
        """Both modes should return a valid pipeline."""
        _, regex_pipeline = regex_results
        _, hybrid_pipeline = hybrid_results
        assert regex_pipeline is not None
        assert hybrid_pipeline is not None
        assert len(regex_pipeline.stages) > 0
        assert len(hybrid_pipeline.stages) > 0
