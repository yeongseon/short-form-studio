from __future__ import annotations

import base64
import os
import tempfile
from importlib import import_module
from pathlib import Path
from unittest import mock

import pytest

UnsafePathComponent = import_module("creator_domain.sanitize").UnsafePathComponent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_factory", "method_name", "payload_factory", "call_kwargs"),
    [
        (
            lambda: __import__(
                "creator_provider.image.dalle_provider", fromlist=["DalleProvider"]
            ).DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3"),
            "generate",
            lambda: {"data": [{"b64_json": base64.b64encode(b"img").decode("utf-8")}]},
            {"prompt": "test"},
        ),
        (
            lambda: __import__(
                "creator_provider.image.stability_provider", fromlist=["StabilityProvider"]
            ).StabilityProvider(endpoint="https://api.stability.ai", model_key="sd3-medium"),
            "generate",
            lambda: b"img",
            {"prompt": "test"},
        ),
        (
            lambda: __import__(
                "creator_provider.image.imagen_provider", fromlist=["ImagenProvider"]
            ).ImagenProvider(
                endpoint="https://generativelanguage.googleapis.com", model_key="imagen-3"
            ),
            "generate",
            lambda: {
                "generatedImages": [
                    {"image": {"imageBytes": base64.b64encode(b"img").decode("utf-8")}}
                ]
            },
            {"prompt": "test"},
        ),
        (
            lambda: __import__(
                "creator_provider.tts.openai_tts_provider", fromlist=["OpenAITTSProvider"]
            ).OpenAITTSProvider(endpoint="https://api.openai.com", model_key="tts-1"),
            "generate",
            lambda: b"audio",
            {"text": "test"},
        ),
        (
            lambda: __import__(
                "creator_provider.stt.whisper_provider", fromlist=["WhisperSTTProvider"]
            ).WhisperSTTProvider(endpoint="https://stt.local", model_key="whisper-small"),
            "transcribe",
            lambda: {"segments": [], "text": ""},
            {},
        ),
    ],
)
async def test_providers_reject_output_path_traversal(
    provider_factory, method_name, payload_factory, call_kwargs, tmp_path: Path
) -> None:
    artifact_root = tmp_path / "artifacts"
    bad_path = str(artifact_root / ".." / "outside" / "x.bin")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
        audio_file.write(b"\x00" * 44)
        audio_input = audio_file.name

    mock_response = mock.MagicMock()
    mock_response.raise_for_status = mock.MagicMock()
    payload = payload_factory()
    if isinstance(payload, bytes):
        mock_response.content = payload
    else:
        mock_response.json.return_value = payload

    env = {
        "OPENAI_API_KEY": "sk-test",
        "STABILITY_API_KEY": "st-test",
        "GOOGLE_API_KEY": "gk-test",
        "ARTIFACT_ROOT": str(artifact_root),
    }
    with (
        mock.patch.dict(os.environ, env, clear=False),
        mock.patch("httpx.AsyncClient.post", return_value=mock_response),
    ):
        provider = provider_factory()
        method = getattr(provider, method_name)
        params = {"output_path": bad_path}

        with pytest.raises(UnsafePathComponent):
            if method_name == "transcribe":
                await method(audio_input, params=params)
            else:
                await method(params=params, **call_kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_factory", "method_name", "payload_factory", "call_kwargs", "suffix"),
    [
        (
            lambda: __import__(
                "creator_provider.image.dalle_provider", fromlist=["DalleProvider"]
            ).DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3"),
            "generate",
            lambda: {"data": [{"b64_json": base64.b64encode(b"img").decode("utf-8")}]},
            {"prompt": "test"},
            ".png",
        ),
        (
            lambda: __import__(
                "creator_provider.image.stability_provider", fromlist=["StabilityProvider"]
            ).StabilityProvider(endpoint="https://api.stability.ai", model_key="sd3-medium"),
            "generate",
            lambda: b"img",
            {"prompt": "test"},
            ".png",
        ),
        (
            lambda: __import__(
                "creator_provider.image.imagen_provider", fromlist=["ImagenProvider"]
            ).ImagenProvider(
                endpoint="https://generativelanguage.googleapis.com", model_key="imagen-3"
            ),
            "generate",
            lambda: {
                "generatedImages": [
                    {"image": {"imageBytes": base64.b64encode(b"img").decode("utf-8")}}
                ]
            },
            {"prompt": "test"},
            ".png",
        ),
        (
            lambda: __import__(
                "creator_provider.tts.openai_tts_provider", fromlist=["OpenAITTSProvider"]
            ).OpenAITTSProvider(endpoint="https://api.openai.com", model_key="tts-1"),
            "generate",
            lambda: b"audio",
            {"text": "test"},
            ".mp3",
        ),
        (
            lambda: __import__(
                "creator_provider.stt.whisper_provider", fromlist=["WhisperSTTProvider"]
            ).WhisperSTTProvider(endpoint="https://stt.local", model_key="whisper-small"),
            "transcribe",
            lambda: {"segments": [], "text": ""},
            {},
            ".srt",
        ),
    ],
)
async def test_providers_accept_output_path_within_artifact_root(
    provider_factory, method_name, payload_factory, call_kwargs, suffix, tmp_path: Path
) -> None:
    artifact_root = tmp_path / "artifacts"
    good_path = artifact_root / "101" / f"file{suffix}"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
        audio_file.write(b"\x00" * 44)
        audio_input = audio_file.name

    mock_response = mock.MagicMock()
    mock_response.raise_for_status = mock.MagicMock()
    payload = payload_factory()
    if isinstance(payload, bytes):
        mock_response.content = payload
    else:
        mock_response.json.return_value = payload

    env = {
        "OPENAI_API_KEY": "sk-test",
        "STABILITY_API_KEY": "st-test",
        "GOOGLE_API_KEY": "gk-test",
        "ARTIFACT_ROOT": str(artifact_root),
    }
    with (
        mock.patch.dict(os.environ, env, clear=False),
        mock.patch("httpx.AsyncClient.post", return_value=mock_response),
    ):
        provider = provider_factory()
        method = getattr(provider, method_name)
        params = {"output_path": str(good_path)}

        if method_name == "transcribe":
            await method(audio_input, params=params)
        else:
            await method(params=params, **call_kwargs)

    assert good_path.exists()
