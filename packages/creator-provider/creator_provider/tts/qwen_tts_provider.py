from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile
from typing import Any

import httpx

from creator_provider.base import AudioResult, TTSProvider


class QwenTTSProvider(TTSProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key

    async def generate(
        self,
        text: str,
        voice: str = "default",
        params: dict[str, Any] | None = None,
    ) -> AudioResult:
        merged_params: dict[str, Any] = dict(params or {})
        payload: dict[str, Any] = {
            "text": text,
            "voice_id": voice,
            "language": merged_params.get("language", os.getenv("TTS_DEFAULT_LANGUAGE", "ko")),
            "speed": merged_params.get("speed", 1.0),
        }

        url = f"{self.endpoint}/synthesize"
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to connect to Qwen3 TTS provider at {url}: {exc}") from exc

        audio_bytes = response.content
        requested_output = merged_params.get("output_path")
        if requested_output:
            output_path = Path(str(requested_output))
        else:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                output_path = Path(tmp.name)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

        duration = _wav_duration_seconds(audio_bytes)
        return AudioResult(
            audio_path=str(output_path),
            duration_seconds=duration,
            model_key=self.model_key,
        )


def _wav_duration_seconds(audio_bytes: bytes) -> float:
    if len(audio_bytes) < 44:
        return 0.0

    num_channels = struct.unpack("<H", audio_bytes[22:24])[0]
    sample_rate = struct.unpack("<I", audio_bytes[24:28])[0]
    bits_per_sample = struct.unpack("<H", audio_bytes[34:36])[0]
    data_size = struct.unpack("<I", audio_bytes[40:44])[0]

    bytes_per_second = sample_rate * num_channels * (bits_per_sample / 8.0)
    if bytes_per_second <= 0:
        return 0.0

    return float(data_size) / float(bytes_per_second)
