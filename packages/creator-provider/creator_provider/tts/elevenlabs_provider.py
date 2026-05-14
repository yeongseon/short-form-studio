from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import AudioResult, TTSProvider
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_TTS_TEXT_CHARS, validate_prompt_length


class ElevenLabsProvider(TTSProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint.rstrip("/")
        self.model_key: str = model_key
        api_key = resolve_api_key("elevenlabs")
        if api_key is None:
            raise ValueError("API key for 'elevenlabs' not configured")
        self.api_key: str = api_key

    async def generate(
        self,
        text: str,
        voice: str = "default",
        params: dict[str, Any] | None = None,
    ) -> AudioResult:
        validate_prompt_length(text, MAX_TTS_TEXT_CHARS, "TTS")
        merged_params = dict(params or {})
        voice_id = (
            voice
            if voice != "default"
            else merged_params.get(
                "voice_id",
                os.getenv("ELEVENLABS_DEFAULT_VOICE", "21m00Tcm4TlvDq8ikWAM"),
            )
        )
        model_id = merged_params.get("model_id", "eleven_multilingual_v2")
        stability = merged_params.get("stability", 0.5)
        similarity_boost = merged_params.get("similarity_boost", 0.75)
        output_format = merged_params.get("output_format", "mp3_44100_128")

        url = f"{self.endpoint}/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    params={"output_format": output_format},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "ElevenLabs API request failed") from exc

        audio_bytes = response.content
        if not audio_bytes:
            raise ProviderError("ElevenLabs API returned empty response")

        output_path_str = merged_params.get("output_path")
        if output_path_str:
            output_path = Path(str(output_path_str))
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
