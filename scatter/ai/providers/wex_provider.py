"""WEX AI Platform provider — stubbed for future integration.

The WEX AI Platform is the company's centralized AI gateway, providing
rate limiting, security controls, and model routing for all internal
AI consumers. This provider will be the primary (default) AI backend
for Scatter once the API contract is finalized.

Until then, all methods raise NotImplementedError with guidance on
using the Gemini provider as a temporary alternative.
"""

import logging
import os
from typing import Optional, Set

from scatter.ai.base import (
    AIProvider,
    AITaskType,
    AnalysisResult,
)

_STUB_MSG = (
    "WEX AI Platform provider is not yet implemented. "
    "Use --google-api-key with the Gemini provider in the meantime. "
    "See: https://github.com/mat-mathews/wex_scatter#ai-providers"
)


class WexProvider(AIProvider):
    """WEX AI Platform provider (stubbed).

    This provider will integrate with the WEX AI Platform's centralized
    API gateway, which handles:
    - Rate limiting and quota management
    - Security and compliance controls
    - Model routing and versioning
    - Usage tracking and cost attribution

    Once the API contract is available, this class will implement the
    full AIProvider protocol. Until then, instantiation succeeds (so
    configuration can be validated) but all analysis calls raise
    NotImplementedError.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "default",
        endpoint: Optional[str] = None,
    ):
        self._model_name = model_name

        resolved_api_key = api_key or os.getenv("WEX_AI_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "WEX AI API key not found. Set the WEX_AI_API_KEY "
                "environment variable or pass api_key."
            )

        self._api_key = resolved_api_key
        self._endpoint = endpoint or os.getenv(
            "WEX_AI_ENDPOINT", "https://ai.wexinc.com"
        )

        logging.info(
            f"WEX AI Platform provider initialized "
            f"(model={model_name}, endpoint={self._endpoint}). "
            f"Note: provider is stubbed — calls will raise NotImplementedError."
        )

    @property
    def name(self) -> str:
        return f"wex:{self._model_name}"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def max_context_size(self) -> int:
        # Placeholder — will be set based on WEX AI Platform model capabilities
        return 128_000

    def supports(self, task_type: AITaskType) -> bool:
        # The WEX AI Platform is expected to support all task types
        # once implemented via its model routing layer.
        return task_type in (
            AITaskType.SUMMARIZATION,
            AITaskType.SYMBOL_EXTRACTION,
            AITaskType.WORK_REQUEST_PARSING,
            AITaskType.RISK_ASSESSMENT,
            AITaskType.COUPLING_NARRATIVE,
            AITaskType.IMPACT_NARRATIVE,
            AITaskType.COMPLEXITY_ESTIMATE,
        )

    def estimate_tokens(self, context: str) -> int:
        return len(context) // 4

    def analyze(self, prompt: str, context: str, task_type: AITaskType) -> AnalysisResult:
        """Not yet implemented — awaiting WEX AI Platform API contract."""
        raise NotImplementedError(_STUB_MSG)

    def extract_affected_symbols(
        self, file_content: str, diff_text: str, file_path: str
    ) -> Optional[Set[str]]:
        """Not yet implemented — awaiting WEX AI Platform API contract."""
        raise NotImplementedError(_STUB_MSG)
