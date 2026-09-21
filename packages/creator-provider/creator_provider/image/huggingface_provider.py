from __future__ import annotations

import asyncio
import os
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderError, ProviderTimeoutError
from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS, validate_prompt_length

# Free models (no HF token needed for serverless inference)
_DEFAULT_MODEL = "black-forest-labs/FLUX.1-schnell"
_FALLBACK_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
_API_URL = "https://router.huggingface.co/hf-inference/models"

# Maximum image dimensions to prevent resource exhaustion
_MAX_WIDTH = 1536
_MAX_HEIGHT = 2048


class HuggingFaceImageProvider(ImageProvider):
    """Free image generation via HuggingFace Inference API — no API key required for free models."""

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint
        self.model_key: str = model_key
        # Use HF_TOKEN if available for higher rate limits, but not required
        self._token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

    async def _make_request(self, prompt: str, model: str, width: int, height: int) -> bytes:
        """Make async HTTP request to HuggingFace Inference API."""
        url = f"{_API_URL}/{model}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        payload: dict[str, Any] = {
            "inputs": prompt,
            "parameters": {"width": width, "height": height},
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 429:
            from creator_provider.exceptions import RateLimitError

            raise RateLimitError("HuggingFace rate limited (429)")

        if response.status_code == 503:
            # Model is loading — retry once after wait
            await asyncio.sleep(20)
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            raise ProviderError(
                f"HuggingFace API error {response.status_code}: {response.text[:200]}"
            )

        content_type = response.headers.get("content-type", "")
        if "image" not in content_type and "octet" not in content_type:
            raise ProviderError(f"HuggingFace returned non-image content: {content_type}")

        return response.content

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        validate_prompt_length(prompt, MAX_IMAGE_PROMPT_CHARS, "Image")
        merged = dict(params or {})
        width = max(64, min(int(merged.get("width", 768)), _MAX_WIDTH))
        height = max(64, min(int(merged.get("height", 1344)), _MAX_HEIGHT))

        # Never allow user-supplied params to override the model — use registry model only
        merged.pop("model", None)

        # Determine output path
        output_path_str = merged.get("output_path")
        if output_path_str:
            candidate_output = str(output_path_str)
            artifact_root = os.getenv("ARTIFACT_ROOT")
            validated_output = import_module("creator_domain.sanitize").validate_artifact_path(
                candidate_output,
                artifact_root or "data/artifacts",
            )
            output_path = Path(validated_output)
        else:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                output_path = Path(tmp.name)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            image_bytes = await self._make_request(prompt, _DEFAULT_MODEL, width, height)
        except (ProviderError, ProviderTimeoutError):
            raise
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"HuggingFace request timed out: {exc}") from exc
        except Exception as exc:
            # Try fallback model
            try:
                image_bytes = await self._make_request(prompt, _FALLBACK_MODEL, width, height)
            except Exception as fallback_exc:
                raise ProviderError(
                    f"HuggingFace image generation failed (both models): {exc}"
                ) from fallback_exc

        output_path.write_bytes(image_bytes)

        return ImageResult(
            image_path=str(output_path),
            width=width,
            height=height,
            model_key=self.model_key,
        )
