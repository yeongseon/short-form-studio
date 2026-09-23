from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from creator_provider.base import ImageProvider
from creator_provider.exceptions import (
    ProviderAuthError, ProviderError, ProviderTimeoutError, ProviderValidationError, RateLimitError,
)
from creator_provider.image.groq_svg_provider import GroqSvgImageProvider
from creator_provider.image.huggingface_provider import HuggingFaceImageProvider


@dataclass(frozen=True, slots=True)
class HttpCase:
    provider: ImageProvider
    handler: Mock
    sleep: AsyncMock
    output: Path


@pytest.fixture(params=["groq", "hf"])
def http_case(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
              tmp_path: Path) -> HttpCase:
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-private-key")
    monkeypatch.setenv("HF_TOKEN", "synthetic-private-key")
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    provider = (GroqSvgImageProvider("offline", "groq-svg") if request.param == "groq"
                else HuggingFaceImageProvider("offline", "hf-flux-schnell"))
    handler = Mock(return_value=httpx.Response(429, headers={"Retry-After": "73"}))
    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)
    return HttpCase(provider, handler, sleep, tmp_path / "image.png")


@pytest.mark.asyncio
async def test_rate_limit_is_one_attempt_without_sleep(http_case: HttpCase) -> None:
    # Given an actual HTTP adapter receiving 429.
    case = http_case
    # When generation is attempted.
    with pytest.raises(RateLimitError) as caught:
        await case.provider.generate("private prompt", {"output_path": str(case.output)})
    # Then Celery owns the retry; the adapter preserves the upstream hint.
    assert caught.value.retry_after == "73"
    assert case.handler.call_count == 1
    case.sleep.assert_not_awaited()
    assert not case.output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error_type", [
    (401, ProviderAuthError), (403, ProviderAuthError),
    (400, ProviderValidationError), (422, ProviderValidationError), (500, ProviderError),
])
async def test_http_status_preserves_type(http_case: HttpCase, status: int,
                                        error_type: type[ProviderError]) -> None:
    # Given a provider response with sensitive body text.
    case = http_case
    case.handler.return_value = httpx.Response(status, text="synthetic-private-value")
    # When the actual adapter handles the response.
    with pytest.raises(error_type) as caught:
        await case.provider.generate("private prompt", {"output_path": str(case.output)})
    # Then classification and source redaction survive without a retry.
    assert type(caught.value) is error_type
    assert "synthetic-private-value" not in str(caught.value)
    assert case.handler.call_count == 1
    case.sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout,
                                      httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError])
async def test_transport_failure_preserves_classification(http_case: HttpCase,
                                                        error_type: type[httpx.HTTPError]) -> None:
    # Given a transport failure containing sensitive diagnostics.
    case = http_case
    case.handler.side_effect = error_type("synthetic-private-value")
    expected = ProviderError if error_type is httpx.RemoteProtocolError else ProviderTimeoutError
    # When generation crosses the real HTTP boundary.
    with pytest.raises(expected) as caught:
        await case.provider.generate("private prompt", {"output_path": str(case.output)})
    # Then no fallback, sleep, or raw diagnostic replaces the typed failure.
    assert type(caught.value) is expected
    assert "synthetic-private-value" not in str(caught.value)
    assert case.handler.call_count == 1
    case.sleep.assert_not_awaited()
