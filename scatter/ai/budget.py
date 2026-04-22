"""AI call budget tracking and rate-limited model proxy.

Provides a centralized budget tracker (AIBudget) and a model proxy
(RateLimitedModel) that enforces call caps and retries transient errors
with exponential backoff + jitter.  Wrapping the model at construction
time means every call path — task modules, provider.analyze(), module-level
helper functions — goes through the proxy automatically.
"""

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_CALL_WARNING_THRESHOLD = 50
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds
_BACKOFF_CAP = 30.0  # seconds

# Transient error types from google.api_core.exceptions.
# Matched by class __name__ (not isinstance) to avoid importing
# google.api_core when AI is not used.  Coupled to Google's naming.
_TRANSIENT_EXCEPTION_NAMES = frozenset(
    {"ResourceExhausted", "TooManyRequests", "ServiceUnavailable", "InternalServerError"}
)


class BudgetExhaustedError(Exception):
    """Raised when the AI call budget has been exhausted.

    Intentionally non-fatal — caught by task modules' existing
    ``except Exception`` handlers.  The message is written so it
    doesn't look like a bug in the logs.
    """


@dataclass
class AIBudget:
    """Tracks AI API call counts and enforces an optional cap.

    Thread safety: all counter mutations are protected by a
    threading.Lock, allowing safe concurrent use from
    ThreadPoolExecutor workers during parallel AI enrichment.

    Note: RateLimitedModel.generate_content() calls can_proceed()
    then record_call() non-atomically. Under concurrent threads,
    this may slightly overshoot max_calls (two threads both pass
    can_proceed before either records). This is acceptable — the
    budget is advisory and the alternative (holding the lock across
    the HTTP call) would serialize all AI calls.
    """

    max_calls: Optional[int] = None
    calls_made: int = field(default=0, init=False)
    calls_skipped: int = field(default=0, init=False)
    _warned_at_threshold: bool = field(default=False, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def can_proceed(self) -> bool:
        """Check whether another call is allowed (no side effects)."""
        with self._lock:
            if self.max_calls is None:
                return True
            return self.calls_made < self.max_calls

    def record_call(self) -> None:
        """Record a completed AI call and warn at threshold."""
        with self._lock:
            self.calls_made += 1
            if (
                self.max_calls is not None
                and self.calls_made > self.max_calls
            ):
                logging.debug(
                    f"AI budget slightly exceeded: {self.calls_made}/{self.max_calls} "
                    f"(concurrent overshoot)"
                )
            if (
                not self._warned_at_threshold
                and self.calls_made >= _CALL_WARNING_THRESHOLD
                and (self.max_calls is None or self.max_calls > _CALL_WARNING_THRESHOLD)
            ):
                logging.warning(
                    f"AI call count has reached {self.calls_made}. "
                    f"Consider using --max-ai-calls to set a budget."
                )
                self._warned_at_threshold = True

    def record_skip(self) -> None:
        """Record a skipped call (budget exhausted)."""
        with self._lock:
            self.calls_skipped += 1

    def summary(self) -> dict:
        """Return a JSON-serializable summary of AI usage."""
        with self._lock:
            return {
                "calls_made": self.calls_made,
                "calls_skipped": self.calls_skipped,
                "max_calls": self.max_calls,
            }


def _is_transient(exc: Exception) -> bool:
    """Check if an exception is a transient API error worth retrying."""
    return type(exc).__name__ in _TRANSIENT_EXCEPTION_NAMES


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter: base * 2^attempt + random(0, base)."""
    delay = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_CAP)
    jitter = random.uniform(0, _BACKOFF_BASE)
    return float(delay + jitter)


class RateLimitedModel:
    """Proxy that wraps a model's generate_content() with budget + backoff.

    Transparently intercepts all AI calls going through the model object.
    All other attributes are proxied to the underlying model.
    """

    def __init__(self, model: Any, budget: AIBudget):
        # Use object.__setattr__ to avoid triggering __getattr__
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_budget", budget)

    def generate_content(self, *args: Any, **kwargs: Any) -> Any:
        """Call the wrapped model with budget enforcement and retry logic.

        Note: retries on transient errors do not count against the budget —
        only successful calls are recorded.  This means a budget of N may
        trigger up to N * _MAX_RETRIES actual API requests in the worst case.
        """
        budget: AIBudget = object.__getattribute__(self, "_budget")
        model = object.__getattribute__(self, "_model")

        if not budget.can_proceed():
            budget.record_skip()
            raise BudgetExhaustedError(
                f"AI budget exhausted ({budget.calls_made}/{budget.max_calls} calls used) "
                f"— use --max-ai-calls to increase"
            )

        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = model.generate_content(*args, **kwargs)
                budget.record_call()
                return response
            except Exception as exc:
                last_exc = exc
                if _is_transient(exc) and attempt < _MAX_RETRIES - 1:
                    delay = _backoff_delay(attempt)
                    logging.warning(
                        f"Transient AI error ({type(exc).__name__}), "
                        f"retrying in {delay:.1f}s (attempt {attempt + 1}/{_MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    continue
                # Non-transient or final attempt — let it propagate
                if attempt == _MAX_RETRIES - 1 and _is_transient(exc):
                    logging.warning(
                        "AI provider unavailable after retries "
                        "— analysis continues without AI enrichment"
                    )
                raise

        # Should not reach here, but satisfy type checker
        raise last_exc  # type: ignore[misc]

    def __getattr__(self, name: str) -> Any:
        """Proxy all other attribute access to the underlying model."""
        return getattr(object.__getattribute__(self, "_model"), name)
