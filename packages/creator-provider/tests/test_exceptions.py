from creator_provider.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderTimeoutError,
    ProviderValidationError,
    RateLimitError,
)


def test_exception_hierarchy() -> None:
    assert issubclass(ProviderTimeoutError, ProviderError)
    assert issubclass(RateLimitError, ProviderError)
    assert issubclass(ProviderValidationError, ProviderError)
    assert issubclass(ProviderAuthError, ProviderError)


def test_exceptions_are_catchable() -> None:
    caught: list[str] = []

    for exc in (
        ProviderError("base"),
        ProviderTimeoutError("timeout"),
        RateLimitError("rate"),
        ProviderValidationError("validation"),
        ProviderAuthError("auth"),
    ):
        try:
            raise exc
        except ProviderError:
            caught.append(type(exc).__name__)

    assert caught == [
        "ProviderError",
        "ProviderTimeoutError",
        "RateLimitError",
        "ProviderValidationError",
        "ProviderAuthError",
    ]
