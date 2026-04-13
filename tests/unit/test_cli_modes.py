"""Smoke tests for mode handlers in scatter.analysis."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scatter.analysis import (
    ModeResult,
    _apply_graph_enrichment,
    run_git_analysis,
    run_target_analysis,
    run_sproc_analysis,
)


class TestModeResult:
    def test_dataclass_defaults(self):
        r = ModeResult()
        assert r.all_results == []
        assert r.filter_pipeline is None
        assert r.graph_enriched is False


class TestRunTargetAnalysis:
    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="GalaxyWorks.Data")
    def test_returns_mode_result(self, mock_ns, mock_fc, make_mode_context):
        mock_fc.return_value = ([], None)
        ctx = make_mode_context()
        target = Path("/tmp/scope/Foo/Foo.csproj")

        result = run_target_analysis(ctx, target)

        assert isinstance(result, ModeResult)
        assert result.all_results == []
        assert result.filter_pipeline is None

    @patch("scatter.compat.v1_bridge._build_consumer_results")
    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="Foo.Ns")
    def test_calls_v1_bridge_on_consumers(self, mock_ns, mock_fc, mock_bridge, make_mode_context):
        consumer = {
            "consumer_name": "Bar",
            "consumer_path": Path("/tmp/scope/Bar/Bar.csproj"),
            "relevant_files": [],
        }
        mock_fc.return_value = ([consumer], MagicMock())

        ctx = make_mode_context()
        target = Path("/tmp/scope/Foo/Foo.csproj")

        run_target_analysis(ctx, target)

        mock_bridge.assert_called_once()
        call_kwargs = mock_bridge.call_args
        assert call_kwargs[1]["target_project_name"] == "Foo"

    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="Foo.Ns")
    def test_uses_explicit_namespace(self, mock_ns, mock_fc, make_mode_context):
        mock_fc.return_value = ([], None)
        ctx = make_mode_context(target_namespace="Custom.Ns")
        target = Path("/tmp/scope/Foo/Foo.csproj")

        run_target_analysis(ctx, target)

        # find_consumers should receive the explicit namespace, not the derived one
        call_args = mock_fc.call_args
        assert call_args[0][2] == "Custom.Ns"
        # derive_namespace should not have been called
        mock_ns.assert_not_called()

    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value=None)
    def test_raises_when_no_namespace(self, mock_ns, mock_fc, make_mode_context):
        ctx = make_mode_context()
        target = Path("/tmp/scope/Foo/Foo.csproj")

        with pytest.raises(ValueError, match="Could not derive target namespace"):
            run_target_analysis(ctx, target)

    @patch("scatter.compat.v1_bridge._build_consumer_results")
    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="Foo.Ns")
    def test_trigger_level_with_class_and_method(
        self, mock_ns, mock_fc, mock_bridge, make_mode_context
    ):
        consumer = {
            "consumer_name": "Bar",
            "consumer_path": Path("/tmp/scope/Bar/Bar.csproj"),
            "relevant_files": [],
        }
        mock_fc.return_value = ([consumer], MagicMock())
        ctx = make_mode_context(class_name="MyClass", method_name="DoStuff")
        target = Path("/tmp/scope/Foo/Foo.csproj")

        run_target_analysis(ctx, target)

        call_kwargs = mock_bridge.call_args[1]
        assert call_kwargs["triggering_info"] == "MyClass.DoStuff"


class TestRunSprocAnalysis:
    @patch("scatter.compat.v1_bridge._build_consumer_results")
    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="GW.Data")
    @patch("scatter.scanners.sproc_scanner.find_cs_files_referencing_sproc")
    def test_accumulates_across_classes(
        self, mock_sproc, mock_ns, mock_fc, mock_bridge, make_mode_context
    ):
        proj = Path("/tmp/scope/GW/GW.csproj")
        mock_sproc.return_value = {
            proj: {
                "ClassA": [Path("/tmp/a.cs")],
                "ClassB": [Path("/tmp/b.cs")],
            }
        }
        consumer = {
            "consumer_name": "Consumer1",
            "consumer_path": Path("/tmp/scope/C1/C1.csproj"),
            "relevant_files": [],
        }
        mock_fc.return_value = ([consumer], MagicMock())

        ctx = make_mode_context()
        result = run_sproc_analysis(ctx, "dbo.sp_Test", None)

        assert isinstance(result, ModeResult)
        # Bridge called once per class (2 classes)
        assert mock_bridge.call_count == 2

    @patch("scatter.scanners.sproc_scanner.find_cs_files_referencing_sproc")
    def test_returns_empty_when_no_sproc_refs(self, mock_sproc, make_mode_context):
        mock_sproc.return_value = {}
        ctx = make_mode_context()

        result = run_sproc_analysis(ctx, "dbo.sp_Missing", None)
        assert result.all_results == []
        assert result.filter_pipeline is None

    @patch("scatter.compat.v1_bridge._build_consumer_results")
    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="GW.Data")
    @patch("scatter.scanners.sproc_scanner.find_cs_files_referencing_sproc")
    def test_class_name_filter(self, mock_sproc, mock_ns, mock_fc, mock_bridge, make_mode_context):
        proj = Path("/tmp/scope/GW/GW.csproj")
        mock_sproc.return_value = {
            proj: {
                "ClassA": [Path("/tmp/a.cs")],
                "ClassB": [Path("/tmp/b.cs")],
            }
        }
        mock_fc.return_value = ([], MagicMock())

        ctx = make_mode_context(class_name="ClassA")
        run_sproc_analysis(ctx, "dbo.sp_Test", None)

        # find_consumers should only be called for ClassA, not ClassB
        assert mock_fc.call_count == 1
        call_args = mock_fc.call_args
        assert call_args[1]["class_name"] == "ClassA"


class TestRunGitAnalysis:
    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_no_changes_returns_empty(self, mock_analyze, make_mode_context):
        mock_analyze.return_value = {}
        ctx = make_mode_context()
        result = run_git_analysis(
            ctx,
            Path("/tmp/repo"),
            "feature/x",
            "main",
            False,
        )
        assert isinstance(result, ModeResult)
        assert result.all_results == []

    @patch("scatter.compat.v1_bridge._build_consumer_results")
    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="MyApp")
    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_multi_type_accumulation(
        self, mock_analyze, mock_ns, mock_fc, mock_bridge, make_mode_context, tmp_path
    ):
        # Set up a fake repo with a csproj and a CS file
        proj_dir = tmp_path / "MyApp"
        proj_dir.mkdir()
        csproj = proj_dir / "MyApp.csproj"
        csproj.write_text("<Project/>")
        cs_file = proj_dir / "Foo.cs"
        cs_file.write_text("public class Foo {}\npublic class Bar {}")

        mock_analyze.return_value = {
            "MyApp/MyApp.csproj": ["MyApp/Foo.cs"],
        }

        consumer = {
            "consumer_name": "Consumer1",
            "consumer_path": tmp_path / "C1" / "C1.csproj",
            "relevant_files": [],
        }
        mock_fc.return_value = ([consumer], MagicMock())

        ctx = make_mode_context(search_scope=tmp_path)
        run_git_analysis(
            ctx,
            tmp_path,
            "feature/x",
            "main",
            False,
        )

        # find_consumers called once per type (Foo and Bar)
        assert mock_fc.call_count == 2
        # bridge called once per type that has consumers
        assert mock_bridge.call_count == 2

    @patch("scatter.analyzers.consumer_analyzer.find_consumers")
    @patch("scatter.scanners.project_scanner.derive_namespace", return_value="MyApp")
    @patch("scatter.analyzers.git_analyzer.analyze_branch_changes")
    def test_class_name_filter(self, mock_analyze, mock_ns, mock_fc, make_mode_context, tmp_path):
        proj_dir = tmp_path / "MyApp"
        proj_dir.mkdir()
        csproj = proj_dir / "MyApp.csproj"
        csproj.write_text("<Project/>")
        cs_file = proj_dir / "Foo.cs"
        cs_file.write_text("public class Foo {}\npublic class Bar {}")

        mock_analyze.return_value = {
            "MyApp/MyApp.csproj": ["MyApp/Foo.cs"],
        }
        mock_fc.return_value = ([], MagicMock())

        ctx = make_mode_context(search_scope=tmp_path, class_name="Foo")
        run_git_analysis(
            ctx,
            tmp_path,
            "feature/x",
            "main",
            False,
        )

        # Only Foo should be analyzed, not Bar
        assert mock_fc.call_count == 1
        assert mock_fc.call_args[0][3] == "Foo"


class TestApplyGraphEnrichment:
    @patch("scatter.analyzers.graph_enrichment.enrich_legacy_results")
    def test_enriches_when_graph_ctx_present(self, mock_enrich, make_mode_context):
        graph_ctx = MagicMock()
        ctx = make_mode_context(no_graph=True)
        ctx.graph_ctx = graph_ctx
        results = [{"ConsumerProjectName": "Foo"}]

        _apply_graph_enrichment(results, ctx)

        mock_enrich.assert_called_once_with(results, graph_ctx)

    def test_no_op_when_no_results(self, make_mode_context):
        ctx = make_mode_context(no_graph=True)
        ctx.graph_ctx = MagicMock()
        # Should not raise
        _apply_graph_enrichment([], ctx)

    def test_no_op_when_no_graph(self, make_mode_context):
        ctx = make_mode_context(no_graph=True)
        # graph_ctx is None by default
        _apply_graph_enrichment([{"foo": "bar"}], ctx)
        assert ctx.graph_ctx is None

    @patch("scatter.analyzers.graph_enrichment.build_graph_context")
    def test_ensure_builds_graph_on_first_call(self, mock_build, make_mode_context):
        mock_build.return_value = MagicMock()
        ctx = make_mode_context(no_graph=False)

        _apply_graph_enrichment([], ctx)

        assert ctx.graph_ctx is not None
        assert ctx.graph_enriched is True
