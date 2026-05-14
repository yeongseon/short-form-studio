from __future__ import annotations

import os
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import AudioResult, TTSProvider
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_TTS_TEXT_CHARS, validate_prompt_length


class OpenAITTSProvider(TTSProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint.rstrip("/")
        self.model_key: str = model_key
        api_key = resolve_api_key("openai")
        if api_key is None:
            raise ValueError("API key for 'openai' not configured")
        self.api_key: str = api_key

    async def generate(
        self,
        text: str,
        voice: str = "default",
        params: dict[str, Any] | None = None,
    ) -> AudioResult:
        validate_prompt_length(text, MAX_TTS_TEXT_CHARS, "TTS")
        merged_params = dict(params or {})
        voice_name = voice if voice != "default" else merged_params.get("voice", "alloy")
        model = merged_params.get("model", "tts-1")
        response_format = merged_params.get("response_format", "mp3")
        speed = merged_params.get("speed", 1.0)
        timeout = float(merged_params.get("timeout", 120.0))

        url = f"{self.endpoint}/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": text,
            "voice": voice_name,
            "response_format": response_format,
            "speed": speed,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "OpenAI TTS API request failed") from exc

        audio_bytes = response.content
        if not audio_bytes:
            raise ProviderError("OpenAI TTS API returned empty response")

        output_path_str = merged_params.get("output_path")
        if output_path_str:
            candidate_output = str(output_path_str)
            artifact_root = os.getenv("ARTIFACT_ROOT")
            validated_output = import_module("creator_domain.sanitize").validate_artifact_path(
                candidate_output,
                artifact_root or "data/artifacts",
            )
            output_path = Path(validated_output)
        else:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                output_path = Path(tmp.name)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

        duration = _estimate_mp3_duration(audio_bytes)
        return AudioResult(
            audio_path=str(output_path),
            duration_seconds=duration,
            model_key=self.model_key,
        )


def _estimate_mp3_duration(audio_bytes: bytes) -> float:
    if len(audio_bytes) < 100:
        return 0.0
    bytes_per_second = 128 * 1000 / 8
    return float(len(audio_bytes)) / float(bytes_per_second)
