"""Provider exception mapping tests — verify httpx errors map to correct ProviderError subclasses.

Covers:
- TimeoutException → ProviderTimeoutError
- ConnectError → ProviderTimeoutError
- NetworkError → ProviderTimeoutError
- HTTP 429 → RateLimitError
- Other HTTP errors → ProviderError
- Exception inheritance chain
"""

from __future__ import annotations

import httpx
import pytest

from creator_provider.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderTimeoutError,
    ProviderValidationError,
    RateLimitError,
    map_httpx_error,
)


class TestMapHttpxError:
    def test_timeout_exception(self):
        exc = httpx.TimeoutException("read timed out")
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderTimeoutError)
        assert "TimeoutException" in str(result)
        assert "read timed out" not in str(result)

    def test_connect_error(self):
        exc = httpx.ConnectError("Connection refused")
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderTimeoutError)

    def test_network_error(self):
        exc = httpx.NetworkError("DNS resolution failed")
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderTimeoutError)

    def test_http_429_rate_limit(self):
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(429, request=request)
        exc = httpx.HTTPStatusError("429", request=request, response=response)
        result = map_httpx_error(exc, "test")
        assert isinstance(result, RateLimitError)

    def test_http_500_generic(self):
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(500, request=request)
        exc = httpx.HTTPStatusError("500", request=request, response=response)
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderError)
        assert not isinstance(result, (ProviderTimeoutError, RateLimitError))

    def test_http_401_maps_to_auth_error(self):
        """HTTP 401 maps to ProviderAuthError."""
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(401, request=request)
        exc = httpx.HTTPStatusError("401", request=request, response=response)
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderAuthError)

    def test_http_403_maps_to_auth_error(self):
        """HTTP 403 maps to ProviderAuthError."""
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(403, request=request)
        exc = httpx.HTTPStatusError("403", request=request, response=response)
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderAuthError)

    def test_http_400_maps_to_validation_error(self):
        """HTTP 400 maps to ProviderValidationError."""
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(400, request=request)
        exc = httpx.HTTPStatusError("400", request=request, response=response)
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderValidationError)

    def test_http_422_maps_to_validation_error(self):
        """HTTP 422 maps to ProviderValidationError."""
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(422, request=request)
        exc = httpx.HTTPStatusError("422", request=request, response=response)
        result = map_httpx_error(exc, "test")
        assert isinstance(result, ProviderValidationError)

    def test_prefix_omitted_when_containing_configured_endpoint(self):
        # Given a caller-owned diagnostic containing an internal endpoint.
        exc = httpx.TimeoutException("timed out")
        # When the shared mapper creates a public summary.
        result = map_httpx_error(exc, "Ollama at http://localhost:11434")
        # Then classification survives but configuration does not.
        assert type(result) is ProviderTimeoutError
        assert str(result) == "Provider: TimeoutException"


@pytest.mark.parametrize("prefix", [
    "SD at http://internal.invalid/private", "HTTPS://USER:PASS@internal.invalid/gsk_path",
    "postgresql://user:password@db.invalid/private", "Bearer synthetic-credential",
    "gsk_synthetic", "AIzaSynthetic", "sk-proj-synthetic_private",
    "arbitrary opaque credential", "", "x" * 100_000,
])
@pytest.mark.parametrize("status,expected", [
    (401, ProviderAuthError), (403, ProviderAuthError),
    (400, ProviderValidationError), (422, ProviderValidationError),
    (429, RateLimitError), (500, ProviderError),
])
def test_summary_discards_prefix_when_mapping_http_status(
    prefix: str, status: int, expected: type[ProviderError],
) -> None:
    # Given untrusted prefix, HTTP diagnostics, body and delay metadata.
    request = httpx.Request("POST", "https://user:password@internal.invalid/private")
    response = httpx.Response(status, request=request, text="private body",
                              headers={"Retry-After": "73"})
    exc = httpx.HTTPStatusError("private diagnostic", request=request, response=response)
    # When mapping the status independently of caller diagnostics.
    result = map_httpx_error(exc, prefix)
    # Then output is bounded and classification/metadata remain exact.
    assert type(result) is expected
    assert str(result) == f"Provider: HTTP {status}"
    if isinstance(result, RateLimitError):
        assert result.retry_after == "73"


class OpaquePrefix(str):
    def __str__(self) -> str:
        raise AssertionError("prefix must not be stringified")

    def __repr__(self) -> str:
        raise AssertionError("prefix must not be represented")

    def __format__(self, format_spec: str) -> str:
        raise AssertionError("prefix must not be formatted")


@pytest.mark.parametrize("error_type,expected", [
    (httpx.ReadTimeout, ProviderTimeoutError), (httpx.ConnectError, ProviderTimeoutError),
    (httpx.ReadError, ProviderTimeoutError), (httpx.RemoteProtocolError, ProviderError),
    (httpx.HTTPError, ProviderError),
])
def test_summary_never_formats_prefix_when_mapping_transport_error(
    error_type: type[httpx.HTTPError], expected: type[ProviderError],
) -> None:
    # Given an opaque string object satisfying the declared prefix contract.
    prefix = OpaquePrefix("private diagnostic")
    exc = error_type("private transport diagnostic")
    # When mapping a transport exception.
    result = map_httpx_error(exc, prefix)
    # Then neither str/repr/format is invoked on the prefix.
    assert type(result) is expected
    assert str(result) == f"Provider: {error_type.__name__}"


class TestExceptionHierarchy:
    """Verify all provider exceptions inherit from ProviderError."""

    def test_timeout_is_provider_error(self):
        assert issubclass(ProviderTimeoutError, ProviderError)

    def test_rate_limit_is_provider_error(self):
        assert issubclass(RateLimitError, ProviderError)

    def test_validation_is_provider_error(self):
        assert issubclass(ProviderValidationError, ProviderError)

    def test_auth_is_provider_error(self):
        assert issubclass(ProviderAuthError, ProviderError)

    def test_provider_error_is_runtime_error(self):
        assert issubclass(ProviderError, RuntimeError)

    def test_all_subtypes_catchable(self):
        """All provider exception types can be caught by except ProviderError."""
        for cls in (
            ProviderTimeoutError,
            RateLimitError,
            ProviderValidationError,
            ProviderAuthError,
        ):
            try:
                raise cls("test")
            except ProviderError:
                pass  # expected
            except Exception:
                pytest.fail(f"{cls.__name__} not caught by ProviderError handler")
