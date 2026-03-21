"""Backward-compatible wrappers for AI/Gemini functions.

Provides the old function signatures (accepting raw model_instance) that
delegate to the canonical implementations in scatter.ai.providers.gemini_provider.
"""

import logging
from typing import Optional, Set

from scatter.ai.providers.gemini_provider import (
    extract_affected_symbols_from_model,
    summarize_file_with_model,
)

# Global kept for backward compatibility — code that reads scatter.gemini_model
gemini_model = None


def configure_gemini(api_key: Optional[str] = None, model_name: str = "gemini-2.0-flash") -> bool:
    """Backward-compatible wrapper. Creates a GeminiProvider and stores its model globally."""
    global gemini_model
    if gemini_model:
        return True

    try:
        from scatter.ai.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key=api_key, model_name=model_name)
        gemini_model = provider.model
        return True
    except (ValueError, Exception) as e:
        logging.error(f"Error configuring Generative AI: {e}")
        logging.error("Ensure the API key is valid and has permissions for the Gemini API.")
        gemini_model = None
        return False


def get_affected_symbols_from_diff(
    file_content: str, diff_text: str, file_path: str, model_instance
) -> Optional[Set[str]]:
    """Backward-compatible wrapper — delegates to gemini_provider module function."""
    return extract_affected_symbols_from_model(model_instance, file_content, diff_text, file_path)


def summarize_csharp_file_with_gemini(
    model_instance, csharp_code: str, file_path_for_log: str
) -> Optional[str]:
    """Backward-compatible wrapper — delegates to gemini_provider module function."""
    return summarize_file_with_model(model_instance, csharp_code, file_path_for_log)
