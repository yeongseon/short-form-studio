"""Tests for ElevenLabs voice_id URL injection prevention."""

from __future__ import annotations

import httpx
import pytest

from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> ElevenLabsProvider:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    return ElevenLabsProvider(endpoint="https://api.elevenlabs.io", model_key="eleven_multilingual_v2")


def _make_response(url: str) -> httpx.Response:
    request = httpx.Request("POST", url)
    return httpx.Response(200, content=b"\xff" * 200, request=request)


@pytest.mark.asyncio
async def test_path_traversal_voice_id_is_encoded(provider: ElevenLabsProvider, monkeypatch: pytest.MonkeyPatch) -> None:
    """A voice_id containing path traversal sequences must be percent-encoded."""
    captured_urls: list[str] = []

    async def _fake_post(self, url, **kwargs):
        captured_urls.append(str(url))
        return _make_response(str(url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await provider.generate(text="hello", voice="../v2/admin")

    assert len(captured_urls) == 1
    assert "/../" not in captured_urls[0]
    assert "%2F" in captured_urls[0] or "%2f" in captured_urls[0]


@pytest.mark.asyncio
async def test_normal_voice_id_unchanged(provider: ElevenLabsProvider, monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal alphanumeric voice_id must pass through unmodified."""
    captured_urls: list[str] = []

    async def _fake_post(self, url, **kwargs):
        captured_urls.append(str(url))
        return _make_response(str(url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await provider.generate(text="hello", voice="21m00Tcm4TlvDq8ikWAM")

    assert captured_urls[0].endswith("/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM")


@pytest.mark.asyncio
async def test_special_chars_voice_id_encoded(provider: ElevenLabsProvider, monkeypatch: pytest.MonkeyPatch) -> None:
    """Voice IDs with special characters (spaces, slashes, queries) are encoded."""
    captured_urls: list[str] = []

    async def _fake_post(self, url, **kwargs):
        captured_urls.append(str(url))
        return _make_response(str(url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    await provider.generate(text="hello", voice="bad/voice?id=1&x=2")

    url = captured_urls[0]
    assert "/bad/" not in url
    assert "?" not in url.split("/v1/text-to-speech/")[1]


@pytest.mark.asyncio
async def test_empty_voice_id_raises_error(provider: ElevenLabsProvider) -> None:
    """Empty or whitespace-only voice_id must raise ProviderError."""
    from creator_provider.exceptions import ProviderError

    with pytest.raises(ProviderError, match="voice_id must not be empty"):
        await provider.generate(text="hello", voice="")

    with pytest.raises(ProviderError, match="voice_id must not be empty"):
        await provider.generate(text="hello", voice="   ")
