"""Provider exception hierarchy."""


class ProviderError(Exception):
    """Base exception for all provider errors."""


class ProviderTimeoutError(ProviderError):
    """Provider request timed out - retryable."""


class RateLimitError(ProviderError):
    """Provider rate limit exceeded - retryable with longer backoff."""


class ProviderValidationError(ProviderError):
    """Invalid input to provider - non-retryable."""


class ProviderAuthError(ProviderError):
    """Authentication/authorization failure - non-retryable."""
