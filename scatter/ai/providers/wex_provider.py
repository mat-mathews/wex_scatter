"""WEX AI Gateway provider — routes LLM calls through the WEX AI Platform proxy.

Uses the OpenAI-compatible API exposed by the WEX AI Gateway. The gateway
handles model routing, rate limiting, security controls, and cost attribution.
"""

import json
import logging
import os
from typing import Any, Optional, Set

from openai import OpenAI

from scatter.ai.base import (
    AIProvider,
    AITaskType,
    AnalysisResult,
    MAX_SUMMARIZATION_CHARS,
    SUMMARIZATION_PROMPT_TEMPLATE,
    redact_credentials,
)

_DEFAULT_ENDPOINT = "https://aips-ai-gateway.dev.ai-platform.int.wexfabric.com/"
_DEFAULT_MODEL = "gemini-2.5-flash"


class _WexResponse:
    """Adapts OpenAI ChatCompletion to the generate_content() response shape."""

    def __init__(self, text: str):
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    @property
    def parts(self) -> list:
        return [self._text] if self._text else []

    @property
    def prompt_feedback(self) -> Optional[str]:
        return None


class _WexModel:
    """Adapter that exposes generate_content() over the OpenAI client.

    This lets existing task modules (which call model.generate_content(prompt))
    work transparently with the WEX Gateway without any changes.
    """

    def __init__(self, client: OpenAI, model_name: str):
        self._client = client
        self._model_name = model_name

    def generate_content(self, prompt: str, **kwargs: Any) -> _WexResponse:
        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        return _WexResponse(text.strip())


class WexProvider(AIProvider):
    """WEX AI Gateway provider.

    Routes LLM calls through the centralized WEX AI Platform gateway,
    which provides rate limiting, security controls, model routing,
    and usage tracking for all internal AI consumers.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = _DEFAULT_MODEL,
        endpoint: Optional[str] = None,
        budget=None,
    ):
        self._model_name = model_name

        resolved_api_key = api_key or os.getenv("WEX_AI_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "WEX AI API key not found. Set the WEX_AI_API_KEY "
                "environment variable or pass api_key."
            )

        self._endpoint = endpoint or os.getenv("WEX_AI_ENDPOINT", _DEFAULT_ENDPOINT)

        client = OpenAI(api_key=resolved_api_key, base_url=self._endpoint)
        self._model: Any = _WexModel(client, model_name)

        if budget is not None:
            from scatter.ai.budget import RateLimitedModel

            self._model = RateLimitedModel(self._model, budget)

        logging.info(
            f"WEX AI Gateway provider initialized (model={model_name}, endpoint={self._endpoint})"
        )

    @property
    def name(self) -> str:
        return f"wex:{self._model_name}"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model(self):
        return self._model

    @property
    def max_context_size(self) -> int:
        return 1_000_000

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
        return len(context) // 4

    def analyze(self, prompt: str, context: str, task_type: AITaskType) -> AnalysisResult:
        full_prompt = f"{prompt}\n\n{context}" if context else prompt
        response = self._model.generate_content(full_prompt)
        return AnalysisResult(response=response.text)

    def summarize_file(self, csharp_code: str, file_path: str) -> Optional[str]:
        from pathlib import Path

        if not csharp_code.strip():
            logging.warning(f"Skipping summarization for empty file: {file_path}")
            return "[File is empty or contains only whitespace]"

        try:
            code_to_send = redact_credentials(
                csharp_code[:MAX_SUMMARIZATION_CHARS], file_path=file_path
            )
            prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
                filename=Path(file_path).name,
                code=code_to_send,
            )

            logging.info(f"Requesting summary for {file_path} from WEX Gateway...")
            response = self._model.generate_content(prompt)

            if not response.parts:
                logging.warning(f"WEX response for {file_path} was empty or blocked.")
                return "[Summary generation blocked or failed]"

            summary = response.text.strip()
            return summary if summary else "[No summary generated]"

        except Exception as e:
            logging.error(
                f"Error during WEX Gateway summarization for {file_path}: {e}",
                exc_info=True,
            )
            return "[Error during summarization]"

    def extract_affected_symbols(
        self, file_content: str, diff_text: str, file_path: str
    ) -> Optional[Set[str]]:
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
            response = self._model.generate_content(prompt)
            response_text = response.text.strip()

            if response_text.startswith("```"):
                lines = response_text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                response_text = "\n".join(lines).strip()

            affected = json.loads(response_text)
            if not isinstance(affected, list):
                logging.warning(f"WEX returned non-list for {file_path}: {response_text}")
                return None

            result = {name for name in affected if isinstance(name, str)}
            logging.info(
                f"Hybrid analysis for {file_path}: {len(result)} affected type(s) "
                f"identified by LLM: {result if result else '(none)'}"
            )
            return result

        except json.JSONDecodeError as e:
            logging.warning(f"Failed to parse WEX JSON response for {file_path}: {e}")
            return None
        except Exception as e:
            logging.warning(f"WEX call failed for {file_path}: {e}")
            return None
