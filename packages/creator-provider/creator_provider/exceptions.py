"""Provider exception hierarchy."""

from __future__ import annotations

import httpx


from creator_domain.provider_errors import (
    ProviderAuthError as ProviderAuthError,
    ProviderError as ProviderError,
    ProviderTimeoutError as ProviderTimeoutError,
    ProviderValidationError as ProviderValidationError,
    RateLimitError as RateLimitError,
)


def map_httpx_error(exc: httpx.HTTPError, prefix: str) -> ProviderError:
    """Map HTTP failures without emitting caller diagnostics.

    ``prefix`` is accepted for call compatibility but deliberately never inspected
    or formatted: existing callers include configured endpoints and credentials.
    Exception chains and text added by callers remain outside this boundary.
    """
    response = getattr(exc, "response", None)
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError)):
        return ProviderTimeoutError(f"Provider: {type(exc).__name__}")
    if response is not None:
        status = response.status_code
        if status == 429:
            error = RateLimitError(f"Provider: HTTP {status}")
            error.retry_after = response.headers.get("Retry-After")
            return error
        if status in (401, 403):
            return ProviderAuthError(f"Provider: HTTP {status}")
        if status in (400, 422):
            return ProviderValidationError(f"Provider: HTTP {status}")
        return ProviderError(f"Provider: HTTP {status}")
    return ProviderError(f"Provider: {type(exc).__name__}")
