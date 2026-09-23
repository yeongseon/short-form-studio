import httpx
import pytest

from creator_provider.exceptions import ProviderTimeoutError, RateLimitError, map_httpx_error


@pytest.mark.parametrize("retry_after", ["73", "Wed, 23 Sep 2026 12:00:00 GMT", None])
def test_rate_limit_preserves_retry_after_when_supplied(retry_after: str | None) -> None:
    # Given an upstream delay hint, including HTTP-date which the scheduler must not parse here.
    request = httpx.Request("POST", "https://provider.invalid")
    response = httpx.Response(
        429, request=request, headers={"Retry-After": retry_after} if retry_after else {},
    )
    error = httpx.HTTPStatusError("rate limited", request=request, response=response)
    # When the shared boundary maps the response.
    mapped = map_httpx_error(error, "Image provider")
    # Then metadata survives without becoming an adapter-owned delay.
    assert isinstance(mapped, RateLimitError)
    assert mapped.retry_after == retry_after


@pytest.mark.parametrize("status", [401, 403, 429, 400, 422, 500, None])
def test_mapping_omits_upstream_diagnostics_when_sensitive(status: int | None) -> None:
    # Given credentials in the URL, header, body, and exception message.
    secret = "synthetic-private-value"
    request = httpx.Request("POST", f"https://provider.invalid/?token={secret}",
                            headers={"Authorization": f"Bearer {secret}"}, content=secret)
    response = httpx.Response(status or 200, request=request, text=secret)
    error = (httpx.HTTPStatusError(secret, request=request, response=response)
             if status else httpx.ReadTimeout(secret, request=request))
    # When mapping source diagnostics for downstream logging/persistence.
    mapped = map_httpx_error(error, "Image provider")
    # Then the summary only contains safe classification information.
    assert secret not in str(mapped)
    assert "provider.invalid" not in str(mapped)
    if status is None:
        assert isinstance(mapped, ProviderTimeoutError)
    else:
        assert str(status) in str(mapped)
