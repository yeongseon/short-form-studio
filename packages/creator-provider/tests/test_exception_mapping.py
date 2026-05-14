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
        assert "read timed out" in str(result)

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

    def test_prefix_included_in_message(self):
        exc = httpx.TimeoutException("timed out")
        result = map_httpx_error(exc, "Ollama at http://localhost:11434")
        assert "Ollama at http://localhost:11434" in str(result)


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
