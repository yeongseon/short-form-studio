"""Provider exception hierarchy."""

from __future__ import annotations

import httpx


class ProviderError(RuntimeError):
    """Base exception for all provider errors."""


class ProviderTimeoutError(ProviderError):
    """Provider request timed out - retryable."""


class RateLimitError(ProviderError):
    """Provider rate limit exceeded - retryable with longer backoff."""


class ProviderValidationError(ProviderError):
    """Invalid input to provider - non-retryable."""


class ProviderAuthError(ProviderError):
    """Authentication/authorization failure - non-retryable."""


def map_httpx_error(exc: httpx.HTTPError, prefix: str) -> ProviderError:
    response = getattr(exc, "response", None)
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError)):
        return ProviderTimeoutError(f"{prefix}: {exc}")
    if response is not None:
        status = response.status_code
        if status == 429:
            return RateLimitError(f"{prefix}: {exc}")
        if status in (401, 403):
            return ProviderAuthError(f"{prefix}: {exc}")
        if status in (400, 422):
            return ProviderValidationError(f"{prefix}: {exc}")
    return ProviderError(f"{prefix}: {exc}")
