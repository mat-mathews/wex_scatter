"""Tests for scatter.ai.providers.wex_provider — WEX AI Gateway integration."""

from unittest.mock import MagicMock, patch

import pytest

from scatter.ai.base import AITaskType, AnalysisResult
from scatter.ai.providers.wex_provider import (
    WexProvider,
    _WexModel,
    _WexResponse,
    _DEFAULT_ENDPOINT,
    _DEFAULT_MODEL,
)


class TestWexResponse:
    def test_text_property(self):
        r = _WexResponse("hello")
        assert r.text == "hello"

    def test_parts_non_empty(self):
        r = _WexResponse("content")
        assert r.parts == ["content"]

    def test_parts_empty_when_no_text(self):
        r = _WexResponse("")
        assert r.parts == []

    def test_prompt_feedback_is_none(self):
        r = _WexResponse("text")
        assert r.prompt_feedback is None


class TestWexModel:
    def test_generate_content_calls_openai_client(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "  response text  "
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )

        model = _WexModel(mock_client, "gemini-2.5-flash")
        result = model.generate_content("test prompt")

        mock_client.chat.completions.create.assert_called_once_with(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "test prompt"}],
        )
        assert isinstance(result, _WexResponse)
        assert result.text == "response text"

    def test_generate_content_handles_none_content(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )

        model = _WexModel(mock_client, "test-model")
        result = model.generate_content("prompt")
        assert result.text == ""
        assert result.parts == []


class TestWexProvider:
    def test_init_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="WEX AI API key not found"):
                WexProvider()

    def test_init_uses_env_var(self):
        with patch.dict("os.environ", {"WEX_AI_API_KEY": "env-key"}):
            provider = WexProvider()
        assert provider.name == f"wex:{_DEFAULT_MODEL}"

    def test_init_uses_explicit_key(self):
        provider = WexProvider(api_key="explicit-key")
        assert provider.model_name == _DEFAULT_MODEL

    def test_init_custom_model(self):
        provider = WexProvider(api_key="key", model_name="gpt-4o")
        assert provider.name == "wex:gpt-4o"
        assert provider.model_name == "gpt-4o"

    def test_init_custom_endpoint(self):
        provider = WexProvider(api_key="key", endpoint="https://custom.wex.com/")
        assert provider._endpoint == "https://custom.wex.com/"

    def test_default_endpoint(self):
        provider = WexProvider(api_key="key")
        assert provider._endpoint == _DEFAULT_ENDPOINT

    def test_endpoint_from_env(self):
        with patch.dict("os.environ", {"WEX_AI_ENDPOINT": "https://staging.wex.com/"}):
            provider = WexProvider(api_key="key")
        assert provider._endpoint == "https://staging.wex.com/"

    def test_max_context_size(self):
        provider = WexProvider(api_key="key")
        assert provider.max_context_size == 1_000_000

    def test_supports_all_task_types(self):
        provider = WexProvider(api_key="key")
        for task_type in (
            AITaskType.SUMMARIZATION,
            AITaskType.SYMBOL_EXTRACTION,
            AITaskType.WORK_REQUEST_PARSING,
            AITaskType.RISK_ASSESSMENT,
            AITaskType.COUPLING_NARRATIVE,
            AITaskType.IMPACT_NARRATIVE,
            AITaskType.COMPLEXITY_ESTIMATE,
            AITaskType.REPORT_SUMMARY,
        ):
            assert provider.supports(task_type)

    def test_does_not_support_boundary_assessment(self):
        provider = WexProvider(api_key="key")
        assert not provider.supports(AITaskType.BOUNDARY_ASSESSMENT)

    def test_estimate_tokens(self):
        provider = WexProvider(api_key="key")
        assert provider.estimate_tokens("a" * 400) == 100

    def test_model_property_returns_adapter(self):
        provider = WexProvider(api_key="key")
        assert provider.model is not None
        assert hasattr(provider.model, "generate_content")

    def test_analyze_calls_model(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse("analysis result")

        result = provider.analyze("prompt", "context", AITaskType.SUMMARIZATION)

        assert isinstance(result, AnalysisResult)
        assert result.response == "analysis result"
        provider._model.generate_content.assert_called_once()
        call_args = provider._model.generate_content.call_args[0][0]
        assert "prompt" in call_args
        assert "context" in call_args

    def test_analyze_empty_context(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse("result")

        result = provider.analyze("prompt only", "", AITaskType.SUMMARIZATION)
        assert result.response == "result"
        call_args = provider._model.generate_content.call_args[0][0]
        assert call_args == "prompt only"

    def test_extract_affected_symbols_parses_json(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse(
            '["MyClass", "IMyInterface"]'
        )

        result = provider.extract_affected_symbols("file content", "diff text", "file.cs")

        assert result == {"MyClass", "IMyInterface"}

    def test_extract_affected_symbols_strips_code_fences(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse(
            '```json\n["MyClass"]\n```'
        )

        result = provider.extract_affected_symbols("content", "diff", "file.cs")
        assert result == {"MyClass"}

    def test_extract_affected_symbols_returns_none_on_bad_json(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse("not json")

        result = provider.extract_affected_symbols("content", "diff", "file.cs")
        assert result is None

    def test_extract_affected_symbols_returns_none_on_non_list(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse('{"key": "value"}')

        result = provider.extract_affected_symbols("content", "diff", "file.cs")
        assert result is None

    def test_summarize_file_empty_code(self):
        provider = WexProvider(api_key="key")
        result = provider.summarize_file("   ", "empty.cs")
        assert result == "[File is empty or contains only whitespace]"

    def test_summarize_file_success(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse("This class does X.")

        result = provider.summarize_file("public class Foo {}", "Foo.cs")
        assert result == "This class does X."

    def test_summarize_file_empty_response(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.return_value = _WexResponse("")

        result = provider.summarize_file("public class Foo {}", "Foo.cs")
        assert result == "[Summary generation blocked or failed]"

    def test_summarize_file_error(self):
        provider = WexProvider(api_key="key")
        provider._model = MagicMock()
        provider._model.generate_content.side_effect = RuntimeError("API down")

        result = provider.summarize_file("public class Foo {}", "Foo.cs")
        assert result == "[Error during summarization]"

    def test_budget_wraps_model(self):
        from scatter.ai.budget import AIBudget, RateLimitedModel

        budget = AIBudget(max_calls=5)
        provider = WexProvider(api_key="key", budget=budget)
        assert isinstance(provider.model, RateLimitedModel)


class TestWexProviderRouterIntegration:
    def test_router_creates_wex_provider(self):
        from scatter.ai.router import AIRouter
        from scatter.config import ScatterConfig, AIConfig

        ai = AIConfig(default_provider="wex", wex_model="gemini-2.5-flash")
        ai.credentials = {"wex": {"api_key": "test-key"}}
        config = ScatterConfig(ai=ai)
        router = AIRouter(config)

        provider = router.get_provider()
        assert provider is not None
        assert provider.name == "wex:gemini-2.5-flash"

    def test_router_wex_with_custom_endpoint(self):
        from scatter.ai.router import AIRouter
        from scatter.config import ScatterConfig, AIConfig

        ai = AIConfig(default_provider="wex")
        ai.credentials = {
            "wex": {
                "api_key": "test-key",
                "endpoint": "https://custom.gateway.wex.com/",
            }
        }
        config = ScatterConfig(ai=ai)
        router = AIRouter(config)

        provider = router.get_provider()
        assert provider is not None
        assert provider._endpoint == "https://custom.gateway.wex.com/"
