"""Smoke tests for scatter.cli_parser."""
import pytest

from scatter.cli_parser import build_parser, _build_cli_overrides, _REDACTED_CLI_KEYS


class TestBuildParser:
    """Verify parser returns expected attributes for known arg combinations."""

    def test_target_mode_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "--target-project", "./Foo/Foo.csproj",
            "--search-scope", "/tmp",
        ])
        assert args.target_project == "./Foo/Foo.csproj"
        assert args.search_scope == "/tmp"
        assert args.branch_name is None

    def test_git_mode_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "--branch-name", "feature/x",
            "--repo-path", "/repo",
            "--base-branch", "develop",
        ])
        assert args.branch_name == "feature/x"
        assert args.repo_path == "/repo"
        assert args.base_branch == "develop"

    def test_sproc_mode_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "--stored-procedure", "dbo.sp_Test",
            "--search-scope", "/tmp",
        ])
        assert args.stored_procedure == "dbo.sp_Test"

    def test_graph_mode(self):
        parser = build_parser()
        args = parser.parse_args(["--graph", "--search-scope", "/tmp"])
        assert args.graph is True

    def test_impact_mode_sow(self):
        parser = build_parser()
        args = parser.parse_args(["--sow", "change the widget", "--search-scope", "/tmp"])
        assert args.sow == "change the widget"

    def test_impact_mode_sow_file(self):
        parser = build_parser()
        args = parser.parse_args(["--sow-file", "sow.txt", "--search-scope", "/tmp"])
        assert args.sow_file == "sow.txt"

    def test_multiprocessing_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["--graph", "--search-scope", "/tmp"])
        assert args.disable_multiprocessing is False
        assert isinstance(args.max_workers, int)
        assert args.max_workers > 0
        assert args.chunk_size > 0

    def test_output_format_choices(self):
        parser = build_parser()
        for fmt in ("console", "csv", "json", "markdown", "mermaid", "pipelines"):
            args = parser.parse_args([
                "--graph", "--search-scope", "/tmp",
                "--output-format", fmt,
            ])
            assert args.output_format == fmt

    def test_modes_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--target-project", "foo.csproj",
                "--branch-name", "main",
                "--search-scope", "/tmp",
            ])

    def test_no_mode_parses_without_error(self):
        """Mode group is optional at parser level (validated in __main__.py for --dump-index support)."""
        parser = build_parser()
        args = parser.parse_args(["--search-scope", "/tmp"])
        assert args.branch_name is None
        assert args.target_project is None


class TestBuildCliOverrides:

    def _make_args(self, **kwargs):
        parser = build_parser()
        base = ["--graph", "--search-scope", "/tmp"]
        return parser.parse_args(base)

    def test_empty_overrides(self):
        parser = build_parser()
        args = parser.parse_args(["--graph", "--search-scope", "/tmp"])
        overrides = _build_cli_overrides(args)
        # Only disable_multiprocessing=False (store_true default) should NOT appear
        assert "multiprocessing.disabled" not in overrides

    def test_google_api_key_override(self):
        parser = build_parser()
        args = parser.parse_args([
            "--graph", "--search-scope", "/tmp",
            "--google-api-key", "test-key",
        ])
        overrides = _build_cli_overrides(args)
        assert overrides["ai.credentials.gemini.api_key"] == "test-key"

    def test_rebuild_graph_override(self):
        parser = build_parser()
        args = parser.parse_args([
            "--graph", "--search-scope", "/tmp",
            "--rebuild-graph",
        ])
        overrides = _build_cli_overrides(args)
        assert overrides["graph.rebuild"] is True

    def test_disable_multiprocessing_override(self):
        parser = build_parser()
        args = parser.parse_args([
            "--graph", "--search-scope", "/tmp",
            "--disable-multiprocessing",
        ])
        overrides = _build_cli_overrides(args)
        assert overrides["multiprocessing.disabled"] is True


class TestRedactedCliKeys:

    def test_google_api_key_is_redacted(self):
        assert 'google_api_key' in _REDACTED_CLI_KEYS
