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

METHOD_SUMMARIZATION_PROMPT_TEMPLATE = """\
Analyze the following C# code from '{filename}'.

The target method being analyzed is: {class_name}.{method_name}

This file is {file_type} code.

For this file, answer:
1. How is {method_name} called? (direct invocation, through interface, via dependency injection, in a loop, etc.)
2. Which method(s) in this file call {method_name}? (list the caller method names)
3. What does the caller do with the return value or side effects?
4. If {method_name}'s signature changed (e.g., new required parameter), what would need to change in this file?
5. Risk level for this caller: Low (test code, easily updated), Medium (business logic, needs review), High (critical path, needs careful coordination)

```csharp
{code}
```

Return a JSON object with:
- "caller_methods": list of method names that call {method_name}
- "call_pattern": how it's called (e.g., "direct invocation in controller action", "called in batch loop")
- "change_impact": what breaks if the signature changes
- "risk": "Low" | "Medium" | "High"
- "summary": 2-3 sentence explanation

Return ONLY the JSON object."""

MAX_SUMMARIZATION_CHARS = 20000


_TEST_FILE_PATTERNS = ("*Test*", "*Mock*", "*Fixture*", "*Fake*", "*Spec*")


def classify_file_type(file_path: str) -> str:
    """Label a file as 'test' or 'production' based on path patterns.

    Checks both the filename and path segments. A file under a ``tests/``
    or ``test/`` directory is labeled as test code even if the filename
    itself doesn't contain a test marker (e.g., ``tests/helpers/Seeder.cs``).
    """
    from fnmatch import fnmatch

    # Check path segments for test directories
    path_lower = file_path.replace("\\", "/").lower()
    for segment in ("/test/", "/tests/", "/testing/"):
        if segment in path_lower:
            return "test"

    # Check filename patterns
    name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    for pattern in _TEST_FILE_PATTERNS:
        if fnmatch(name, pattern):
            return "test"
    return "production"


class AITaskType(Enum):
    SUMMARIZATION = "summarization"
    SYMBOL_EXTRACTION = "symbol_extraction"
    WORK_REQUEST_PARSING = "work_request_parsing"
    RISK_ASSESSMENT = "risk_assessment"
    COUPLING_NARRATIVE = "coupling_narrative"
    IMPACT_NARRATIVE = "impact_narrative"
    COMPLEXITY_ESTIMATE = "complexity_estimate"
    BOUNDARY_ASSESSMENT = "boundary_assessment"
    REPORT_SUMMARY = "report_summary"


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
