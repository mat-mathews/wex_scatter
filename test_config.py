"""Tests for scatter.config and scatter.ai.router."""
import os
import logging
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scatter.config import ScatterConfig, AIConfig, load_config
from scatter.ai.base import AITaskType
from scatter.ai.router import AIRouter


# Env vars the config system reads — cleared by the autouse fixture below
_CONFIG_ENV_VARS = ("GOOGLE_API_KEY", "SCATTER_DEFAULT_PROVIDER", "WEX_AI_API_KEY", "WEX_AI_ENDPOINT")


@pytest.fixture(autouse=True)
def _clean_env():
    """Remove config-relevant env vars so the real environment doesn't leak."""
    with patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                  if k not in _CONFIG_ENV_VARS}):
        yield


# ---------------------------------------------------------------------------
# TestScatterConfig
# ---------------------------------------------------------------------------

class TestScatterConfig:
    """Tests for configuration loading and precedence."""

    def test_default_config(self):
        """Defaults are sensible."""
        config = ScatterConfig()
        assert config.ai.default_provider == "gemini"
        assert config.ai.gemini_model == "gemini-2.0-flash"
        assert config.max_depth == 2
        assert config.disable_multiprocessing is False
        assert config.max_workers is None
        assert config.chunk_size is None
        assert "*/bin/*" in config.exclude_patterns

    def test_load_empty_directory(self, tmp_path):
        """No yaml files -> defaults."""
        config = load_config(repo_root=tmp_path, cli_overrides=None)
        assert config.ai.default_provider == "gemini"
        assert config.max_depth == 2

    def test_load_repo_config(self, tmp_path):
        """.scatter.yaml values applied."""
        yaml_content = (
            "ai:\n"
            "  default_provider: openai\n"
            "  gemini_model: gemini-2.0-flash\n"
            "search:\n"
            "  max_depth: 5\n"
        )
        (tmp_path / ".scatter.yaml").write_text(yaml_content)
        config = load_config(repo_root=tmp_path)
        assert config.ai.default_provider == "openai"
        assert config.ai.gemini_model == "gemini-2.0-flash"
        assert config.max_depth == 5

    def test_load_user_config(self, tmp_path):
        """~/.scatter/config.yaml values applied."""
        user_dir = tmp_path / ".scatter"
        user_dir.mkdir()
        yaml_content = (
            "ai:\n"
            "  gemini_model: gemini-pro\n"
            "multiprocessing:\n"
            "  max_workers: 8\n"
        )
        (user_dir / "config.yaml").write_text(yaml_content)

        with patch("scatter.config.Path.home", return_value=tmp_path):
            config = load_config(repo_root=tmp_path)
        assert config.ai.gemini_model == "gemini-pro"
        assert config.max_workers == 8

    def test_repo_overrides_user(self, tmp_path):
        """Repo config wins over user config."""
        # User config
        user_dir = tmp_path / "home" / ".scatter"
        user_dir.mkdir(parents=True)
        (user_dir / "config.yaml").write_text("ai:\n  gemini_model: user-model\n")

        # Repo config
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".scatter.yaml").write_text("ai:\n  gemini_model: repo-model\n")

        with patch("scatter.config.Path.home", return_value=tmp_path / "home"):
            config = load_config(repo_root=repo_dir)
        assert config.ai.gemini_model == "repo-model"

    def test_cli_overrides_all(self, tmp_path):
        """CLI overrides win over everything."""
        (tmp_path / ".scatter.yaml").write_text("ai:\n  gemini_model: repo-model\n")
        config = load_config(
            repo_root=tmp_path,
            cli_overrides={"ai.gemini_model": "cli-model"},
        )
        assert config.ai.gemini_model == "cli-model"

    def test_env_var_credentials(self, tmp_path):
        """GOOGLE_API_KEY env var flows to ai.credentials.gemini.api_key."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key-123"}):
            config = load_config(repo_root=tmp_path)
        assert config.ai.credentials["gemini"]["api_key"] == "test-key-123"

    def test_env_var_wex_credentials(self, tmp_path):
        """WEX_AI_API_KEY env var flows to ai.credentials.wex.api_key."""
        with patch.dict(os.environ, {"WEX_AI_API_KEY": "wex-key-456"}):
            config = load_config(repo_root=tmp_path)
        assert config.ai.credentials["wex"]["api_key"] == "wex-key-456"

    def test_env_var_wex_endpoint(self, tmp_path):
        """WEX_AI_ENDPOINT env var flows to ai.credentials.wex.endpoint."""
        with patch.dict(os.environ, {"WEX_AI_ENDPOINT": "https://ai-staging.wexinc.com"}):
            config = load_config(repo_root=tmp_path)
        assert config.ai.credentials["wex"]["endpoint"] == "https://ai-staging.wexinc.com"

    def test_env_var_default_provider(self, tmp_path):
        """SCATTER_DEFAULT_PROVIDER env var sets default provider."""
        with patch.dict(os.environ, {"SCATTER_DEFAULT_PROVIDER": "anthropic"}):
            config = load_config(repo_root=tmp_path)
        assert config.ai.default_provider == "anthropic"

    def test_missing_yaml_files_ignored(self, tmp_path):
        """No errors for missing files."""
        config = load_config(repo_root=tmp_path / "nonexistent")
        assert config.ai.default_provider == "gemini"

    def test_malformed_yaml_ignored(self, tmp_path, caplog):
        """Invalid YAML logs warning, uses defaults."""
        (tmp_path / ".scatter.yaml").write_text(": : : invalid yaml [[[")
        with caplog.at_level(logging.WARNING):
            config = load_config(repo_root=tmp_path)
        assert config.ai.default_provider == "gemini"
        assert any("Could not parse" in r.message for r in caplog.records)

    def test_partial_config(self, tmp_path):
        """YAML with only ai.default_provider merges with defaults for rest."""
        (tmp_path / ".scatter.yaml").write_text("ai:\n  default_provider: anthropic\n")
        config = load_config(repo_root=tmp_path)
        assert config.ai.default_provider == "anthropic"
        assert config.ai.gemini_model == "gemini-2.0-flash"
        assert config.max_depth == 2

    def test_exclude_patterns_from_config(self, tmp_path):
        """search.exclude_patterns replaces defaults (not merges)."""
        yaml_content = (
            "search:\n"
            "  exclude_patterns:\n"
            "    - '*/node_modules/*'\n"
            "    - '*.test.cs'\n"
        )
        (tmp_path / ".scatter.yaml").write_text(yaml_content)
        config = load_config(repo_root=tmp_path)
        assert config.exclude_patterns == ["*/node_modules/*", "*.test.cs"]
        # Defaults are replaced, not merged
        assert "*/bin/*" not in config.exclude_patterns

    def test_credentials_from_yaml(self, tmp_path):
        """Credentials loaded from YAML config."""
        yaml_content = (
            "ai:\n"
            "  credentials:\n"
            "    gemini:\n"
            "      api_key: yaml-key\n"
        )
        (tmp_path / ".scatter.yaml").write_text(yaml_content)
        config = load_config(repo_root=tmp_path)
        assert config.ai.credentials["gemini"]["api_key"] == "yaml-key"

    def test_task_overrides_from_yaml(self, tmp_path):
        """task_overrides loaded from config."""
        yaml_content = (
            "ai:\n"
            "  task_overrides:\n"
            "    work_request_parsing: anthropic\n"
            "    risk_assessment: openai\n"
        )
        (tmp_path / ".scatter.yaml").write_text(yaml_content)
        config = load_config(repo_root=tmp_path)
        assert config.ai.task_overrides["work_request_parsing"] == "anthropic"
        assert config.ai.task_overrides["risk_assessment"] == "openai"

    def test_multiprocessing_config(self, tmp_path):
        """Multiprocessing settings loaded from YAML."""
        yaml_content = (
            "multiprocessing:\n"
            "  disabled: true\n"
            "  max_workers: 4\n"
            "  chunk_size: 100\n"
        )
        (tmp_path / ".scatter.yaml").write_text(yaml_content)
        config = load_config(repo_root=tmp_path)
        assert config.disable_multiprocessing is True
        assert config.max_workers == 4
        assert config.chunk_size == 100


# ---------------------------------------------------------------------------
# TestBuildCliOverrides
# ---------------------------------------------------------------------------

class TestBuildCliOverrides:
    """Tests for _build_cli_overrides in __main__."""

    def test_no_flags_produces_empty(self):
        """When user passes no relevant flags, overrides dict is empty."""
        from scatter.cli_parser import _build_cli_overrides
        args = Namespace(
            google_api_key=None,
            gemini_model=None,
            disable_multiprocessing=False,
            max_depth=None,
        )
        assert _build_cli_overrides(args) == {}

    def test_explicit_default_value_still_overrides(self):
        """User explicitly passing the default value IS captured as override."""
        from scatter.cli_parser import _build_cli_overrides
        args = Namespace(
            google_api_key=None,
            gemini_model="gemini-2.0-flash",  # same as config default
            disable_multiprocessing=False,
            max_depth=2,  # same as config default
        )
        overrides = _build_cli_overrides(args)
        assert overrides["ai.gemini_model"] == "gemini-2.0-flash"
        assert overrides["search.max_depth"] == 2

    def test_all_flags_populated(self):
        """All override-able flags captured."""
        from scatter.cli_parser import _build_cli_overrides
        args = Namespace(
            google_api_key="my-key",
            gemini_model="gemini-2.0-flash",
            disable_multiprocessing=True,
            max_depth=5,
        )
        overrides = _build_cli_overrides(args)
        assert overrides == {
            "ai.credentials.gemini.api_key": "my-key",
            "ai.gemini_model": "gemini-2.0-flash",
            "multiprocessing.disabled": True,
            "search.max_depth": 5,
        }


# ---------------------------------------------------------------------------
# TestAIRouter
# ---------------------------------------------------------------------------

class TestAIRouter:
    """Tests for AI task routing."""

    def _make_config(self, api_key="test-key", **kwargs):
        """Helper to build a ScatterConfig with gemini credentials."""
        ai = AIConfig(**kwargs)
        if api_key:
            ai.credentials = {"gemini": {"api_key": api_key}}
        config = ScatterConfig(ai=ai)
        return config

    @patch("scatter.ai.router.AIRouter._create_gemini")
    def test_get_provider_default(self, mock_create):
        """Returns provider when gemini is default and credentials exist."""
        mock_provider = MagicMock()
        mock_provider.supports.return_value = True
        mock_create.return_value = mock_provider

        config = self._make_config()
        router = AIRouter(config)
        provider = router.get_provider()

        assert provider is mock_provider
        mock_create.assert_called_once()

    def test_get_provider_no_credentials(self, tmp_path):
        """Returns None when credentials are missing."""
        config = load_config(repo_root=tmp_path)
        router = AIRouter(config)
        provider = router.get_provider()
        assert provider is None

    @patch("scatter.ai.router.AIRouter._create_provider")
    def test_get_provider_task_override(self, mock_create):
        """task_overrides routes specific task to specific provider."""
        mock_provider = MagicMock()
        mock_provider.supports.return_value = True
        mock_create.return_value = mock_provider

        config = self._make_config(
            task_overrides={"work_request_parsing": "anthropic"}
        )
        router = AIRouter(config)
        router.get_provider(AITaskType.WORK_REQUEST_PARSING)

        mock_create.assert_called_with("anthropic")

    @patch("scatter.ai.router.AIRouter._create_gemini")
    def test_provider_caching(self, mock_create):
        """Same provider instance returned on repeated calls."""
        mock_provider = MagicMock()
        mock_provider.supports.return_value = True
        mock_create.return_value = mock_provider

        config = self._make_config()
        router = AIRouter(config)
        p1 = router.get_provider()
        p2 = router.get_provider()

        assert p1 is p2
        mock_create.assert_called_once()

    @patch("scatter.ai.router.AIRouter._create_gemini")
    def test_unsupported_task_type(self, mock_create):
        """Provider that doesn't support task returns None."""
        mock_provider = MagicMock()
        mock_provider.supports.return_value = False
        mock_create.return_value = mock_provider

        config = self._make_config()
        router = AIRouter(config)
        provider = router.get_provider(AITaskType.RISK_ASSESSMENT)

        assert provider is None

    def test_unknown_provider_name(self, caplog):
        """Unknown provider returns None with warning."""
        config = ScatterConfig()
        config.ai.default_provider = "nonexistent"
        router = AIRouter(config)

        with caplog.at_level(logging.WARNING):
            provider = router.get_provider()

        assert provider is None
        assert any("Unknown AI provider" in r.message for r in caplog.records)

    @patch("scatter.ai.router.AIRouter._create_wex")
    def test_wex_provider_routing(self, mock_create):
        """Router dispatches to WEX provider when configured."""
        mock_provider = MagicMock()
        mock_provider.supports.return_value = True
        mock_create.return_value = mock_provider

        ai = AIConfig(default_provider="wex")
        ai.credentials = {"wex": {"api_key": "test-wex-key"}}
        config = ScatterConfig(ai=ai)
        router = AIRouter(config)
        provider = router.get_provider()

        assert provider is mock_provider
        mock_create.assert_called_once()

    def test_wex_provider_no_credentials(self, tmp_path):
        """WEX provider returns None when API key is missing."""
        config = load_config(repo_root=tmp_path)
        config.ai.default_provider = "wex"
        router = AIRouter(config)
        provider = router.get_provider()
        assert provider is None

    def test_wex_provider_stub_raises(self):
        """WEX provider methods raise NotImplementedError."""
        from scatter.ai.providers.wex_provider import WexProvider

        provider = WexProvider(api_key="test-key")
        assert provider.name == "wex:default"
        assert provider.supports(AITaskType.SUMMARIZATION)

        with pytest.raises(NotImplementedError, match="not yet implemented"):
            provider.analyze("prompt", "context", AITaskType.SUMMARIZATION)

        with pytest.raises(NotImplementedError, match="not yet implemented"):
            provider.extract_affected_symbols("content", "diff", "file.cs")
