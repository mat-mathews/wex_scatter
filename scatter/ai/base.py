"""AI Provider protocol and shared types."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, runtime_checkable


class AITaskType(Enum):
    SUMMARIZATION = "summarization"
    SYMBOL_EXTRACTION = "symbol_extraction"


@dataclass
class AnalysisResult:
    response: str
    confidence: float = 1.0
    token_usage: Optional[dict] = None
    cost_estimate: Optional[float] = None


@runtime_checkable
class AIProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def max_context_size(self) -> int: ...

    def analyze(self, prompt: str, context: str, task_type: AITaskType) -> AnalysisResult: ...

    def supports(self, task_type: AITaskType) -> bool: ...

    def estimate_tokens(self, context: str) -> int: ...
