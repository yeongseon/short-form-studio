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
