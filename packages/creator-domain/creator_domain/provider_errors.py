"""Provider-neutral failures shared by use cases and I/O adapters."""


class ProviderError(RuntimeError):
    """Base exception for all provider errors."""


class ProviderTimeoutError(ProviderError):
    """Provider request timed out - retryable."""


class RateLimitError(ProviderError):
    """Provider rate limit exceeded - retryable with longer backoff."""

    retry_after: str | int | None = None


class ProviderValidationError(ProviderError):
    """Invalid input to provider - non-retryable."""


class ProviderAuthError(ProviderError):
    """Authentication/authorization failure - non-retryable."""
