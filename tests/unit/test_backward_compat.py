"""Backward compatibility tests for CLI flags and mode dispatch.

Ensures new --pr-risk / --collapsible flags don't break existing behavior.
"""

import subprocess
import textwrap

import pytest

from scatter.cli_parser import build_parser


class TestParserFlags:
    """Fast parser-level tests — no subprocess, no git."""

    def test_pr_risk_flag_default_false(self):
        parser = build_parser()
        args = parser.parse_args(["--branch-name", "feat/x", "--search-scope", "."])
        assert args.pr_risk is False

    def test_collapsible_flag_default_false(self):
        parser = build_parser()
        args = parser.parse_args(["--branch-name", "feat/x", "--pr-risk", "--search-scope", "."])
        assert args.collapsible is False

    def test_collapsible_flag_true(self):
        parser = build_parser()
        args = parser.parse_args(
            ["--branch-name", "feat/x", "--pr-risk", "--collapsible", "--search-scope", "."]
        )
        assert args.pr_risk is True
        assert args.collapsible is True

    def test_collapsible_accepted_without_pr_risk(self):
        """--collapsible is accepted even without --pr-risk (just ignored at runtime)."""
        parser = build_parser()
        args = parser.parse_args(
            ["--branch-name", "feat/x", "--collapsible", "--search-scope", "."]
        )
        assert args.collapsible is True
        assert args.pr_risk is False


class TestModeDispatch:
    """Verify mode routing logic without actually running analysis."""

    def test_branch_mode_dispatch_without_pr_risk(self):
        """--branch-name without --pr-risk should route to run_git_mode."""
        parser = build_parser()
        args = parser.parse_args(["--branch-name", "feat/x", "--search-scope", "."])
        assert args.branch_name == "feat/x"
        assert not getattr(args, "pr_risk", False)

    def test_branch_mode_dispatch_with_pr_risk(self):
        """--branch-name with --pr-risk should route to run_pr_risk_mode."""
        parser = build_parser()
        args = parser.parse_args(["--branch-name", "feat/x", "--pr-risk", "--search-scope", "."])
        assert args.branch_name == "feat/x"
        assert args.pr_risk is True


class TestCliShimReexports:
    """Verify scatter.cli re-exports public API from analysis.py and output.py."""

    def test_analysis_symbols(self):
        from scatter.cli import ModeContext, ModeResult, run_git_analysis
        from scatter.cli import run_target_analysis, run_sproc_analysis
        from scatter.cli import apply_impact_graph_enrichment

        assert ModeContext is not None
        assert ModeResult is not None
        assert callable(run_git_analysis)
        assert callable(run_target_analysis)
        assert callable(run_sproc_analysis)
        assert callable(apply_impact_graph_enrichment)

    def test_output_symbols(self):
        from scatter.cli import dispatch_legacy_output

        assert callable(dispatch_legacy_output)


class TestFunctionalBackwardCompat:
    """Functional test with a real tmp_path git repo."""

    @pytest.fixture()
    def git_repo(self, tmp_path):
        """Create a minimal git repo with a .cs file change on a branch."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create git repo with initial commit
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.local"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        # Create a .csproj and .cs file
        proj_dir = repo / "MyProject"
        proj_dir.mkdir()
        (proj_dir / "MyProject.csproj").write_text(
            textwrap.dedent("""\
                <Project Sdk="Microsoft.NET.Sdk">
                  <PropertyGroup>
                    <TargetFramework>net8.0</TargetFramework>
                    <RootNamespace>MyProject</RootNamespace>
                  </PropertyGroup>
                </Project>
            """)
        )
        (proj_dir / "Widget.cs").write_text(
            textwrap.dedent("""\
                namespace MyProject;
                public class Widget { }
            """)
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True
        )

        # Create feature branch with a new type
        subprocess.run(
            ["git", "checkout", "-b", "feat/new-type"], cwd=repo, capture_output=True, check=True
        )
        (proj_dir / "Gadget.cs").write_text(
            textwrap.dedent("""\
                namespace MyProject;
                public class Gadget { }
            """)
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add Gadget"], cwd=repo, capture_output=True, check=True
        )

        return repo

    def test_git_analysis_returns_mode_result(self, git_repo):
        """run_git_analysis returns ModeResult with ConsumerResult objects (not PRRiskReport)."""
        from scatter.cli import ModeContext, ModeResult, run_git_analysis
        from scatter.config import ScatterConfig
        from scatter.core.models import ConsumerResult

        ctx = ModeContext(
            search_scope=git_repo,
            repo_path=git_repo,
            config=ScatterConfig(),
            pipeline_map={},
            solution_file_cache=[],
            batch_job_map={},
            ai_provider=None,
        )

        result = run_git_analysis(
            ctx,
            repo_path=git_repo,
            branch_name="feat/new-type",
            base_branch="main",
            enable_hybrid=False,
        )

        assert isinstance(result, ModeResult)
        assert isinstance(result.all_results, list)
        # Results may be empty (no consumers in this tiny repo) but type must be correct
        for r in result.all_results:
            assert isinstance(r, ConsumerResult)
