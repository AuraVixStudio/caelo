from __future__ import annotations

from dataclasses import dataclass
import random

from caelo_core.providers.errors import ErrorCategory, normalize_provider_error


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay_seconds: float = 0.0
    message: str = ""


def retry_decision(
    error: BaseException, provider: str, attempt: int, max_attempts: int
) -> RetryDecision:
    normalized = normalize_provider_error(error, provider)
    message = (
        str(error)
        if normalized.category == ErrorCategory.UNKNOWN and str(error)
        else str(normalized)
    )
    if not normalized.retryable or attempt >= max_attempts:
        return RetryDecision(False, message=message)
    base = min(60.0, float(2 ** max(0, attempt - 1)))
    return RetryDecision(True, base * random.uniform(0.8, 1.2), message)
