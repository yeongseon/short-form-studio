from __future__ import annotations

import os
import struct
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from creator_provider.base import AudioResult, TTSProvider
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_TTS_TEXT_CHARS, validate_prompt_length

# CosyVoice instruct mode supports style descriptions for dramatic narration.
# Examples: "用悲伤的语气说", "Speak with excitement", "슬픈 목소리로"
_DEFAULT_INSTRUCT_TEXT = "Speak naturally with clear pronunciation"

# Default speaker for SFT mode (pre-trained voices bundled with CosyVoice)
_DEFAULT_SPEAKER = "中文女"


class CosyVoiceProvider(TTSProvider):
    """High-quality TTS via CosyVoice 3.0 (Apache 2.0, 0.5B model).

    Supports three synthesis modes:
    - instruct: Control emotion/speed/style via text description (default)
    - zero_shot: Clone any voice from a reference audio clip
    - sft: Use pre-trained speaker voices

    Requires a running CosyVoice FastAPI server (see docker/tts-cosyvoice/).
    """

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key

    async def generate(
        self,
        text: str,
        voice: str = "default",
        params: dict[str, Any] | None = None,
    ) -> AudioResult:
        validate_prompt_length(text, MAX_TTS_TEXT_CHARS, "TTS")
        merged_params: dict[str, Any] = dict(params or {})

        # Determine synthesis mode
        mode = merged_params.get("mode", "instruct")

        if mode == "zero_shot":
            audio_bytes = await self._generate_zero_shot(text, voice, merged_params)
        elif mode == "sft":
            audio_bytes = await self._generate_sft(text, voice, merged_params)
        else:
            audio_bytes = await self._generate_instruct(text, voice, merged_params)

        if len(audio_bytes) < 100:
            raise ProviderError("CosyVoice returned empty or invalid audio")

        # Resolve output path
        requested_output = merged_params.get("output_path")
        if requested_output:
            candidate_output = str(requested_output)
            artifact_root = os.getenv("ARTIFACT_ROOT")
            # NOTE: validate-then-write race (symlink swap) is acceptable here;
            # artifact directories are server-controlled and not user-writable.
            validated_output = import_module("creator_domain.sanitize").validate_artifact_path(
                candidate_output,
                artifact_root or "data/artifacts",
            )
            output_path = Path(validated_output)
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

    async def _generate_instruct(self, text: str, voice: str, params: dict[str, Any]) -> bytes:
        """Instruct mode: control speech style via text description.

        Params:
            instruct_text: Style description (e.g. "Speak with excitement and energy")
            speed: Float speed multiplier (default 1.0)
            speaker: Speaker ID for the base voice
        """
        instruct_text = params.get("instruct_text", _DEFAULT_INSTRUCT_TEXT)
        speed = params.get("speed", 1.0)
        speaker = voice if voice != "default" else params.get("speaker", _DEFAULT_SPEAKER)

        payload = {
            "tts_text": text,
            "instruct_text": instruct_text,
            "speed": speed,
            "speaker_id": speaker,
        }

        url = f"{self.endpoint}/inference_instruct"
        return await self._post(url, payload)

    async def _generate_zero_shot(self, text: str, voice: str, params: dict[str, Any]) -> bytes:
        """Zero-shot mode: clone voice from reference audio.

        Params:
            reference_audio: Path to reference audio file (3-10 seconds recommended)
            reference_text: Transcript of the reference audio
            speed: Float speed multiplier (default 1.0)
        """
        reference_audio = params.get("reference_audio")
        if not reference_audio:
            raise ProviderError("CosyVoice zero_shot mode requires 'reference_audio' parameter")
        reference_text = params.get("reference_text", "")
        speed = params.get("speed", 1.0)

        payload = {
            "tts_text": text,
            "prompt_text": reference_text,
            "speed": speed,
        }

        url = f"{self.endpoint}/inference_zero_shot"

        # Send reference audio as multipart file
        ref_path = Path(reference_audio)
        if not ref_path.exists():
            raise ProviderError(f"Reference audio file not found: {reference_audio}")

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                with open(ref_path, "rb") as f:
                    files = {"prompt_wav": (ref_path.name, f, "audio/wav")}
                    response = await client.post(url, data=payload, files=files)
                    response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, f"CosyVoice zero_shot failed at {url}") from exc

        return response.content

    async def _generate_sft(self, text: str, voice: str, params: dict[str, Any]) -> bytes:
        """SFT mode: use pre-trained speaker voice.

        Params:
            speaker: Speaker ID (e.g. "中文女", "中文男", "英文女")
            speed: Float speed multiplier (default 1.0)
        """
        speaker = voice if voice != "default" else params.get("speaker", _DEFAULT_SPEAKER)
        speed = params.get("speed", 1.0)

        payload = {
            "tts_text": text,
            "speaker_id": speaker,
            "speed": speed,
        }

        url = f"{self.endpoint}/inference_sft"
        return await self._post(url, payload)

    async def _post(self, url: str, payload: dict[str, Any]) -> bytes:
        """POST JSON payload and return raw audio bytes."""
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, f"CosyVoice request failed at {url}") from exc

        return response.content


def _wav_duration_seconds(audio_bytes: bytes) -> float:
    """Parse WAV header to compute duration in seconds."""
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
