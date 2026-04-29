"""Tests for test-project exclusion from blast radius analysis."""

import pytest

from scatter.analyzers.consumer_analyzer import is_test_project
from scatter.config import AnalysisConfig, DEFAULT_TEST_PROJECT_PATTERNS
from scatter.core.models import (
    FilterPipeline,
    FilterStage,
    STAGE_DISCOVERY,
    STAGE_PROJECT_REFERENCE,
    STAGE_TEST_EXCLUSION,
)


class TestIsTestProject:
    """Unit tests for the is_test_project() predicate."""

    @pytest.mark.parametrize(
        "name",
        [
            "GalaxyWorks.Api.Tests",
            "GalaxyWorks.Data.Tests",
            "GalaxyWorks.Tests.Integration",
            "GalaxyWorks.UnitTests",
            "GalaxyWorks.IntegrationTests",
            "GalaxyWorks.TestUtils",
            "GalaxyWorks.TestHelpers",
            "GalaxyWorks.Api.Benchmarks",
            "GalaxyWorks.Notifications.Specs",
            "GalaxyWorks.WebPortalPostDeployTests",
        ],
    )
    def test_matches_default_patterns(self, name):
        assert is_test_project(name, DEFAULT_TEST_PROJECT_PATTERNS)

    @pytest.mark.parametrize(
        "name",
        [
            "GalaxyWorks.Api",
            "GalaxyWorks.Data",
            "GalaxyWorks.Notifications",
            "GalaxyWorks.WebPortal",
            "GalaxyWorks.BatchProcessor",
            "TestamentOfFaith",
            "GalaxyWorks.Specification",
        ],
    )
    def test_does_not_match_production_projects(self, name):
        assert not is_test_project(name, DEFAULT_TEST_PROJECT_PATTERNS)

    def test_empty_patterns_matches_nothing(self):
        assert not is_test_project("Foo.Tests", [])

    def test_custom_pattern(self):
        assert is_test_project("Foo.Spec", ["*.Spec"])
        assert not is_test_project("Foo.Spec", ["*.Tests"])

    def test_case_sensitive(self):
        assert not is_test_project("Foo.tests", DEFAULT_TEST_PROJECT_PATTERNS)


class TestAnalysisConfigDefaults:
    """Verify AnalysisConfig ships with test-project exclusion on."""

    def test_exclude_enabled_by_default(self):
        cfg = AnalysisConfig()
        assert cfg.exclude_test_projects is True

    def test_default_patterns_non_empty(self):
        cfg = AnalysisConfig()
        assert len(cfg.test_project_patterns) >= 4

    def test_patterns_are_independent_copies(self):
        a = AnalysisConfig()
        b = AnalysisConfig()
        a.test_project_patterns.append("*.Bogus")
        assert "*.Bogus" not in b.test_project_patterns


class TestFilterPipelineStage:
    """Verify the test_exclusion stage integrates with the pipeline model."""

    def test_arrow_chain_includes_test_exclusion(self):
        pipeline = FilterPipeline(
            search_scope="/repo",
            total_projects_scanned=20,
            total_files_scanned=0,
            stages=[
                FilterStage(STAGE_DISCOVERY, 20, 19),
                FilterStage(STAGE_PROJECT_REFERENCE, 19, 8),
                FilterStage(STAGE_TEST_EXCLUSION, 8, 5),
            ],
        )
        chain = pipeline.format_arrow_chain()
        assert "test-excluded" in chain
        assert "5 test-excluded" in chain

    def test_arrow_chain_skipped_when_no_exclusion(self):
        pipeline = FilterPipeline(
            search_scope="/repo",
            total_projects_scanned=20,
            total_files_scanned=0,
            stages=[
                FilterStage(STAGE_DISCOVERY, 20, 19),
                FilterStage(STAGE_PROJECT_REFERENCE, 19, 8),
            ],
        )
        chain = pipeline.format_arrow_chain()
        assert "test-excluded" not in chain


class TestConsumerAnalyzerIntegration:
    """Integration tests verifying test-project filtering in find_consumers."""

    def test_excludes_test_projects_from_filesystem_discovery(self, tmp_path):
        target = tmp_path / "Target" / "Target.csproj"
        target.parent.mkdir()
        target.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')

        consumer = tmp_path / "Consumer" / "Consumer.csproj"
        consumer.parent.mkdir()
        consumer.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            f'    <ProjectReference Include="../Target/Target.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )

        test_consumer = tmp_path / "Consumer.Tests" / "Consumer.Tests.csproj"
        test_consumer.parent.mkdir()
        test_consumer.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            f'    <ProjectReference Include="../Target/Target.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )

        from scatter.analyzers.consumer_analyzer import find_consumers

        config = AnalysisConfig(exclude_test_projects=True)
        results, pipeline = find_consumers(
            target_csproj_path=target.resolve(),
            search_scope_path=tmp_path,
            target_namespace="Target",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
            analysis_config=config,
        )

        consumer_names = [r["consumer_name"] for r in results]
        assert "Consumer" in consumer_names
        assert "Consumer.Tests" not in consumer_names

        stage_names = [s.name for s in pipeline.stages]
        assert STAGE_TEST_EXCLUSION in stage_names
        test_stage = next(s for s in pipeline.stages if s.name == STAGE_TEST_EXCLUSION)
        assert test_stage.dropped_count == 1

    def test_includes_test_projects_when_disabled(self, tmp_path):
        target = tmp_path / "Target" / "Target.csproj"
        target.parent.mkdir()
        target.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')

        test_consumer = tmp_path / "Consumer.Tests" / "Consumer.Tests.csproj"
        test_consumer.parent.mkdir()
        test_consumer.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            f'    <ProjectReference Include="../Target/Target.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )

        from scatter.analyzers.consumer_analyzer import find_consumers

        config = AnalysisConfig(exclude_test_projects=False)
        results, pipeline = find_consumers(
            target_csproj_path=target.resolve(),
            search_scope_path=tmp_path,
            target_namespace="Target",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
            analysis_config=config,
        )

        consumer_names = [r["consumer_name"] for r in results]
        assert "Consumer.Tests" in consumer_names

    def test_no_exclusion_without_analysis_config(self, tmp_path):
        target = tmp_path / "Target" / "Target.csproj"
        target.parent.mkdir()
        target.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')

        test_consumer = tmp_path / "Consumer.Tests" / "Consumer.Tests.csproj"
        test_consumer.parent.mkdir()
        test_consumer.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            f'    <ProjectReference Include="../Target/Target.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )

        from scatter.analyzers.consumer_analyzer import find_consumers

        results, pipeline = find_consumers(
            target_csproj_path=target.resolve(),
            search_scope_path=tmp_path,
            target_namespace="Target",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True,
            analysis_config=None,
        )

        consumer_names = [r["consumer_name"] for r in results]
        assert "Consumer.Tests" in consumer_names
        stage_names = [s.name for s in pipeline.stages]
        assert STAGE_TEST_EXCLUSION not in stage_names


class TestCLIFlag:
    """Verify --include-test-projects wires through to config."""

    def test_include_test_projects_flag_disables_exclusion(self):
        from scatter.cli_parser import _build_cli_overrides, build_parser

        parser = build_parser()
        args = parser.parse_args(["--target-project", "Foo.csproj", "--include-test-projects"])
        overrides = _build_cli_overrides(args)
        assert overrides.get("analysis.exclude_test_projects") is False

    def test_default_does_not_override(self):
        from scatter.cli_parser import _build_cli_overrides, build_parser

        parser = build_parser()
        args = parser.parse_args(["--target-project", "Foo.csproj"])
        overrides = _build_cli_overrides(args)
        assert "analysis.exclude_test_projects" not in overrides


class TestExactNamePattern:
    """Verify patterns without wildcards work as exact matches."""

    def test_exact_name_matches(self):
        assert is_test_project("MySpecificProject", ["MySpecificProject"])

    def test_exact_name_no_match(self):
        assert not is_test_project("OtherProject", ["MySpecificProject"])
