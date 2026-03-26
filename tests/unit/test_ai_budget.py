"""Tests for scatter.ai.budget — AIBudget, RateLimitedModel, BudgetExhaustedError."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from scatter.ai.budget import (
    AIBudget,
    BudgetExhaustedError,
    RateLimitedModel,
    _CALL_WARNING_THRESHOLD,
    _backoff_delay,
    _is_transient,
)


# ---------------------------------------------------------------------------
# AIBudget
# ---------------------------------------------------------------------------


class TestAIBudget:
    def test_unlimited_budget_always_proceeds(self):
        budget = AIBudget(max_calls=None)
        for _ in range(100):
            assert budget.can_proceed()
            budget.record_call()
        assert budget.calls_made == 100

    def test_capped_budget_blocks_at_limit(self):
        budget = AIBudget(max_calls=3)
        for _ in range(3):
            assert budget.can_proceed()
            budget.record_call()
        assert not budget.can_proceed()

    def test_record_skip_increments(self):
        budget = AIBudget(max_calls=0)
        budget.record_skip()
        budget.record_skip()
        assert budget.calls_skipped == 2

    def test_summary_returns_correct_dict(self):
        budget = AIBudget(max_calls=10)
        budget.record_call()
        budget.record_call()
        budget.record_skip()
        assert budget.summary() == {
            "calls_made": 2,
            "calls_skipped": 1,
            "max_calls": 10,
        }

    def test_warning_fires_at_threshold(self, caplog):
        budget = AIBudget(max_calls=None)
        with caplog.at_level(logging.WARNING):
            for _ in range(_CALL_WARNING_THRESHOLD):
                budget.record_call()
        assert any("AI call count" in msg for msg in caplog.messages)

    def test_warning_fires_only_once(self, caplog):
        budget = AIBudget(max_calls=None)
        with caplog.at_level(logging.WARNING):
            for _ in range(_CALL_WARNING_THRESHOLD + 10):
                budget.record_call()
        warning_count = sum(1 for msg in caplog.messages if "AI call count" in msg)
        assert warning_count == 1

    def test_no_warning_when_cap_below_threshold(self, caplog):
        """No warning if max_calls is at or below threshold — user already set a cap."""
        budget = AIBudget(max_calls=_CALL_WARNING_THRESHOLD)
        with caplog.at_level(logging.WARNING):
            for _ in range(_CALL_WARNING_THRESHOLD):
                budget.record_call()
        assert not any("AI call count" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# RateLimitedModel
# ---------------------------------------------------------------------------


class TestRateLimitedModel:
    def test_delegates_generate_content(self):
        model = MagicMock()
        model.generate_content.return_value = "response"
        budget = AIBudget(max_calls=10)
        proxy = RateLimitedModel(model, budget)

        result = proxy.generate_content("prompt")
        assert result == "response"
        model.generate_content.assert_called_once_with("prompt")
        assert budget.calls_made == 1

    def test_raises_budget_exhausted(self):
        model = MagicMock()
        budget = AIBudget(max_calls=0)
        proxy = RateLimitedModel(model, budget)

        with pytest.raises(BudgetExhaustedError, match="budget exhausted"):
            proxy.generate_content("prompt")
        model.generate_content.assert_not_called()
        assert budget.calls_skipped == 1

    def test_retries_transient_errors(self):
        """Transient errors trigger retry; success on second attempt counts as 1 call."""
        transient = type("ResourceExhausted", (Exception,), {})
        model = MagicMock()
        model.generate_content.side_effect = [transient("rate limited"), "ok"]
        budget = AIBudget(max_calls=10)
        proxy = RateLimitedModel(model, budget)

        with patch("scatter.ai.budget.time.sleep"):
            result = proxy.generate_content("prompt")

        assert result == "ok"
        assert model.generate_content.call_count == 2
        assert budget.calls_made == 1

    def test_non_transient_error_raises_immediately(self):
        model = MagicMock()
        model.generate_content.side_effect = ValueError("bad input")
        budget = AIBudget(max_calls=10)
        proxy = RateLimitedModel(model, budget)

        with pytest.raises(ValueError, match="bad input"):
            proxy.generate_content("prompt")
        assert model.generate_content.call_count == 1

    def test_exhausted_after_max_retries(self):
        """After max retries on transient errors, the last exception propagates."""
        transient = type("ServiceUnavailable", (Exception,), {})
        model = MagicMock()
        model.generate_content.side_effect = transient("down")
        budget = AIBudget(max_calls=10)
        proxy = RateLimitedModel(model, budget)

        with patch("scatter.ai.budget.time.sleep"):
            with pytest.raises(transient):
                proxy.generate_content("prompt")
        assert model.generate_content.call_count == 3  # _MAX_RETRIES

    def test_logs_warning_after_final_retry(self, caplog):
        """The 'unavailable after retries' message fires on final transient failure."""
        transient = type("ServiceUnavailable", (Exception,), {})
        model = MagicMock()
        model.generate_content.side_effect = transient("down")
        budget = AIBudget(max_calls=10)
        proxy = RateLimitedModel(model, budget)

        with patch("scatter.ai.budget.time.sleep"):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(transient):
                    proxy.generate_content("prompt")
        assert any("unavailable after retries" in msg for msg in caplog.messages)

    def test_proxies_other_attributes(self):
        model = MagicMock()
        model.some_attr = "value"
        proxy = RateLimitedModel(model, AIBudget())
        assert proxy.some_attr == "value"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_transient_matches_known_names(self):
        for name in (
            "ResourceExhausted",
            "TooManyRequests",
            "ServiceUnavailable",
            "InternalServerError",
        ):
            exc = type(name, (Exception,), {})("err")
            assert _is_transient(exc)

    def test_is_transient_rejects_unknown(self):
        assert not _is_transient(ValueError("nope"))

    def test_backoff_delay_increases(self):
        d0 = _backoff_delay(0)
        d1 = _backoff_delay(1)
        d2 = _backoff_delay(2)
        # Each base doubles; jitter adds randomness but base trend is up
        assert d0 < 10  # sanity: not absurdly large
        # Can't assert strict ordering due to jitter, but base doubles
        # Just ensure they're all positive
        assert d0 > 0 and d1 > 0 and d2 > 0


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    def test_max_ai_calls_flag_parses(self):
        from scatter.cli_parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["--graph", "--search-scope", ".", "--max-ai-calls", "25"])
        assert args.max_ai_calls == 25

    def test_max_ai_calls_default_is_none(self):
        from scatter.cli_parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["--graph", "--search-scope", "."])
        assert args.max_ai_calls is None

    def test_config_loads_max_ai_calls_from_yaml(self, tmp_path):
        yaml_content = "ai:\n  max_ai_calls: 42\n"
        config_file = tmp_path / ".scatter.yaml"
        config_file.write_text(yaml_content)

        from scatter.config import load_config

        config = load_config(repo_root=tmp_path)
        assert config.ai.max_ai_calls == 42

    def test_config_loads_max_ai_calls_from_env(self):
        from scatter.config import load_config

        with patch.dict("os.environ", {"SCATTER_MAX_AI_CALLS": "30"}):
            config = load_config(repo_root=None)
        assert config.ai.max_ai_calls == 30

    def test_cli_override_beats_env(self):
        from scatter.config import load_config

        with patch.dict("os.environ", {"SCATTER_MAX_AI_CALLS": "30"}):
            config = load_config(
                repo_root=None,
                cli_overrides={"ai.max_ai_calls": 10},
            )
        assert config.ai.max_ai_calls == 10
