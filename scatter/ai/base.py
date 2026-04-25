"""AI Provider protocol and shared types."""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Protocol, Set, Tuple, runtime_checkable

logger = logging.getLogger(__name__)

SUMMARIZATION_PROMPT_TEMPLATE = (
    "Analyze the following C# code from the file '{filename}':\n\n"
    "```csharp\n{code}\n```\n\n"
    "Please provide a concise summary (2-3 sentences) explaining the "
    "primary purpose of the C# code in this file. Focus on what the "
    "main classes/structs/interfaces/enums declared within this specific "
    "file *do*. Do not list methods or properties unless essential for "
    "the summary."
)

MAX_SUMMARIZATION_CHARS = 20000


class AITaskType(Enum):
    SUMMARIZATION = "summarization"
    SYMBOL_EXTRACTION = "symbol_extraction"
    WORK_REQUEST_PARSING = "work_request_parsing"
    RISK_ASSESSMENT = "risk_assessment"
    COUPLING_NARRATIVE = "coupling_narrative"
    IMPACT_NARRATIVE = "impact_narrative"
    COMPLEXITY_ESTIMATE = "complexity_estimate"
    BOUNDARY_ASSESSMENT = "boundary_assessment"


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

    def extract_affected_symbols(
        self, file_content: str, diff_text: str, file_path: str
    ) -> Optional[Set[str]]: ...


# --- Credential scanning ---

_CREDENTIAL_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----")),
    (
        "connection string",
        re.compile(r"(?i)(?:connection\s*string|data\s+source)\s*=\s*[\"']?[^\s;\"']{10,}"),
    ),
    ("password assignment", re.compile(r"(?i)(?:password|passwd|pwd)\s*=\s*[\"'][^\"']{4,}[\"']")),
    (
        "API key assignment",
        re.compile(r"(?i)(?:api[_-]?key|apikey|secret[_-]?key)\s*=\s*[\"'][^\"']{8,}[\"']"),
    ),
]


def redact_credentials(content: str, file_path: str = "") -> str:
    """Scan content for credential patterns and redact matching lines.

    Returns the content with matching lines replaced by [REDACTED: reason].
    Logs a warning for each redaction so operators can audit.
    """
    lines = content.split("\n")
    redacted = False
    for i, line in enumerate(lines):
        for label, pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(line):
                lines[i] = f"[REDACTED: {label}]"
                redacted = True
                break
    if redacted:
        logger.warning(f"Redacted credential patterns from content before AI call ({file_path})")
    return "\n".join(lines)
