"""Gemini AI provider — encapsulates all Google Gemini API interaction.

Core logic lives in module-level functions that accept any model_instance
with a generate_content() method. This allows:
- GeminiProvider methods to delegate to them
- Backward-compat wrappers to call them with MagicMock in tests
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, Set

import google.generativeai as genai

from scatter.ai.base import (
    AIProvider,
    AITaskType,
    AnalysisResult,
    MAX_SUMMARIZATION_CHARS,
    SUMMARIZATION_PROMPT_TEMPLATE,
    redact_credentials,
)


# --- Module-level functions (provider-agnostic) ---
# These accept any object with generate_content() — genai model, MagicMock, etc.


def extract_affected_symbols_from_model(
    model_instance, file_content: str, diff_text: str, file_path: str
) -> Optional[Set[str]]:
    """Analyze a diff to identify meaningfully changed C# type declarations.

    Accepts any object with a generate_content() method.
    Returns a Set of affected type names, or None on failure
    (triggers fallback to regex).
    """
    prompt = f"""Analyze the following C# file and its git diff. Identify which top-level type declarations
(class, struct, interface, enum) had their body, signature, or members meaningfully changed in the diff.

Rules:
- Only return type names whose definition/body/members were actually modified in the diff
- Do NOT include types that merely appear in the same file but were not changed
- For comment-only or using/import-only changes, return an empty array
- Return ONLY a JSON array of type name strings, nothing else
- Example: ["MyClass", "IMyInterface"]

File path: {file_path}

Full file content:
```csharp
{file_content}
```

Git diff:
```diff
{diff_text}
```

Return ONLY the JSON array:"""

    try:
        response = model_instance.generate_content(prompt)
        response_text = response.text.strip()

        # Strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            response_text = "\n".join(lines).strip()

        affected = json.loads(response_text)
        if not isinstance(affected, list):
            logging.warning(f"Gemini returned non-list for {file_path}: {response_text}")
            return None

        result = {name for name in affected if isinstance(name, str)}
        logging.info(
            f"Hybrid analysis for {file_path}: {len(result)} affected type(s) "
            f"identified by LLM: {result if result else '(none - comment/import only change)'}"
        )
        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse Gemini JSON response for {file_path}: {e}")
        return None
    except Exception as e:
        logging.warning(f"Gemini call failed for {file_path}: {e}")
        return None


def summarize_file_with_model(model_instance, csharp_code: str, file_path: str) -> Optional[str]:
    """Summarize a C# file's content using any model with generate_content().

    Accepts any object with a generate_content() method.
    Returns summary text or error string.
    """
    if not model_instance:
        logging.error("Model instance not provided. Cannot summarize.")
        return None

    if not csharp_code.strip():
        logging.warning(f"Skipping summarization for empty or whitespace-only file: {file_path}")
        return "[File is empty or contains only whitespace]"

    try:
        code_to_send = redact_credentials(
            csharp_code[:MAX_SUMMARIZATION_CHARS], file_path=file_path
        )
        prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
            filename=Path(file_path).name,
            code=code_to_send,
        )

        logging.info(f"Requesting summary for {file_path} from Gemini API...")
        safety_settings = [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
        ]
        response = model_instance.generate_content(prompt, safety_settings=safety_settings)
        logging.debug(f"Received Gemini response for {file_path}.")

        if not response.parts:
            logging.warning(
                f"Gemini response for {file_path} was empty or blocked. "
                f"Safety ratings: {response.prompt_feedback}"
            )
            return "[Summary generation blocked or failed]"

        summary = response.text.strip()
        return summary if summary else "[No summary generated]"

    except Exception as e:
        logging.error(
            f"An error occurred while interacting with the Gemini API for {file_path}: {e}",
            exc_info=True,
        )
        return "[Error during summarization]"


# --- GeminiProvider class ---


class GeminiProvider(AIProvider):
    """Encapsulates Google Gemini API configuration and operations.

    Replaces the global gemini_model variable and standalone functions
    (configure_gemini, summarize_csharp_file_with_gemini,
    get_affected_symbols_from_diff) with a single provider instance.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.0-flash",
        budget=None,
    ):
        self._model_name = model_name
        self._model: Any = None

        resolved_api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "Google API Key not found. Set the GOOGLE_API_KEY "
                "environment variable or pass api_key."
            )

        logging.debug(
            f"Configuring Gemini with API key "
            f"(source: {'Argument' if api_key else 'Environment Variable'})..."
        )
        genai.configure(api_key=resolved_api_key)
        self._model = genai.GenerativeModel(model_name)

        if budget is not None:
            from scatter.ai.budget import RateLimitedModel

            self._model = RateLimitedModel(self._model, budget)

        logging.info(f"Gemini configured successfully using model '{model_name}'.")

    @property
    def name(self) -> str:
        return f"gemini:{self._model_name}"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model(self):
        """Access the underlying genai GenerativeModel instance."""
        return self._model

    @property
    def max_context_size(self) -> int:
        return 1_000_000  # Gemini 1.5 Flash context window

    def supports(self, task_type: AITaskType) -> bool:
        return task_type in (
            AITaskType.SUMMARIZATION,
            AITaskType.SYMBOL_EXTRACTION,
            AITaskType.WORK_REQUEST_PARSING,
            AITaskType.RISK_ASSESSMENT,
            AITaskType.COUPLING_NARRATIVE,
            AITaskType.IMPACT_NARRATIVE,
            AITaskType.COMPLEXITY_ESTIMATE,
            AITaskType.REPORT_SUMMARY,
        )

    def estimate_tokens(self, context: str) -> int:
        # Rough estimate: ~4 chars per token for English/code
        return len(context) // 4

    def analyze(self, prompt: str, context: str, task_type: AITaskType) -> AnalysisResult:
        """Generic analysis — sends prompt + context to Gemini."""
        full_prompt = f"{prompt}\n\n{context}" if context else prompt
        if self._model is None:
            raise RuntimeError("GeminiProvider model not initialized")
        response = self._model.generate_content(full_prompt)
        return AnalysisResult(response=response.text.strip())

    def summarize_file(self, csharp_code: str, file_path: str) -> Optional[str]:
        """Summarize a C# file's content."""
        return summarize_file_with_model(self._model, csharp_code, file_path)

    def extract_affected_symbols(
        self, file_content: str, diff_text: str, file_path: str
    ) -> Optional[Set[str]]:
        """Analyze a diff to identify meaningfully changed C# type declarations."""
        return extract_affected_symbols_from_model(self._model, file_content, diff_text, file_path)
