from pathlib import Path

import httpx
import pytest

from creator_provider.exceptions import ProviderAuthError
from creator_provider.image.sd_local_provider import SDLocalProvider
from creator_provider.llm.ollama_provider import OllamaProvider
from creator_provider.tts.cosyvoice_provider import CosyVoiceProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [SDLocalProvider, OllamaProvider, CosyVoiceProvider])
async def test_summary_omits_endpoint_when_configured_provider_returns_401(
    provider_type: type[SDLocalProvider | OllamaProvider | CosyVoiceProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a real adapter configured with synthetic userinfo and a token-bearing path.
    provider = provider_type("https://synthetic-user:synthetic-password@internal.invalid/gsk_path", "test")
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, text="private upstream body")

    client_type = httpx.AsyncClient

    def client(*, timeout: float) -> httpx.AsyncClient:
        return client_type(timeout=timeout, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    # When the real generate entrypoint reaches its HTTP error boundary.
    with pytest.raises(ProviderAuthError) as caught:
        await provider.generate("test prompt")
    # Then the actual endpoint was used, but none of it becomes summary text.
    assert len(requests) == 1
    assert requests[0].url.host == "internal.invalid"
    assert requests[0].url.path.startswith("/gsk_path/")
    assert requests[0].headers["authorization"].startswith("Basic ")
    assert type(caught.value) is ProviderAuthError
    assert str(caught.value) == "Provider: HTTP 401"


@pytest.mark.asyncio
async def test_summary_omits_endpoint_when_cosyvoice_zero_shot_returns_401(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Given a synthetic reference file and configured credential-bearing endpoint.
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"synthetic reference")
    provider = CosyVoiceProvider("https://user:password@internal.invalid/gsk_path", "test")
    client_type = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/gsk_path/inference_zero_shot"
        return httpx.Response(401, text="private upstream body")

    def client(*, timeout: float) -> httpx.AsyncClient:
        return client_type(timeout=timeout, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    # When generate follows the multipart zero-shot boundary.
    with pytest.raises(ProviderAuthError) as caught:
        await provider.generate("test", params={"mode": "zero_shot", "reference_audio": str(reference)})
    # Then the separately implemented HTTP catch also has a safe summary.
    assert type(caught.value) is ProviderAuthError
    assert str(caught.value) == "Provider: HTTP 401"
