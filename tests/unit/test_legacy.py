"""Tests for scatter._legacy — backward-compatible Gemini wrappers."""

from unittest.mock import MagicMock, patch

from scatter._legacy import (
    configure_gemini,
    get_affected_symbols_from_diff,
    summarize_csharp_file_with_gemini,
)


class TestConfigureGemini:
    def test_returns_false_on_failure(self):
        with patch("scatter.ai.providers.gemini_provider.GeminiProvider", side_effect=ValueError("no key")):
            import scatter._legacy as mod

            mod.gemini_model = None
            result = configure_gemini(api_key="bad")
            assert result is False
            assert mod.gemini_model is None

    def test_returns_true_when_already_configured(self):
        import scatter._legacy as mod

        mod.gemini_model = MagicMock()
        try:
            result = configure_gemini()
            assert result is True
        finally:
            mod.gemini_model = None

    def test_configures_provider(self):
        import scatter._legacy as mod

        mod.gemini_model = None
        mock_provider = MagicMock()
        mock_provider.model = MagicMock()
        with patch("scatter.ai.providers.gemini_provider.GeminiProvider", return_value=mock_provider):
            result = configure_gemini(api_key="test-key")
            assert result is True
            assert mod.gemini_model is mock_provider.model
        mod.gemini_model = None


class TestGetAffectedSymbols:
    @patch("scatter._legacy.extract_affected_symbols_from_model")
    def test_delegates_to_provider(self, mock_extract):
        mock_extract.return_value = {"Foo", "Bar"}
        model = MagicMock()
        result = get_affected_symbols_from_diff("content", "diff", "file.cs", model)
        mock_extract.assert_called_once_with(model, "content", "diff", "file.cs")
        assert result == {"Foo", "Bar"}


class TestSummarizeCsharpFile:
    @patch("scatter._legacy.summarize_file_with_model")
    def test_delegates_to_provider(self, mock_summarize):
        mock_summarize.return_value = "Summary text"
        model = MagicMock()
        result = summarize_csharp_file_with_gemini(model, "code", "path.cs")
        mock_summarize.assert_called_once_with(model, "code", "path.cs")
        assert result == "Summary text"
