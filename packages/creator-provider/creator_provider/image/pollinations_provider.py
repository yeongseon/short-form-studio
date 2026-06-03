from __future__ import annotations

import os
import tempfile
import urllib.parse
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS, validate_prompt_length


class PollinationsProvider(ImageProvider):
    """Free image generation via Pollinations.ai — no API key required."""

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint.rstrip("/")
        self.model_key: str = model_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        validate_prompt_length(prompt, MAX_IMAGE_PROMPT_CHARS, "Image")
        merged = dict(params or {})
        width = int(merged.get("width", 1024))
        height = int(merged.get("height", 1792))
        timeout = float(merged.get("timeout", 120.0))

        encoded_prompt = urllib.parse.quote(prompt, safe="")
        url = f"{self.endpoint}/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "Pollinations.ai image request failed") from exc

        image_bytes = response.content
        if not image_bytes or len(image_bytes) < 100:
            raise ProviderError("Pollinations.ai returned empty or invalid image")

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
        output_path.write_bytes(image_bytes)

        return ImageResult(
            image_path=str(output_path),
            width=width,
            height=height,
            model_key=self.model_key,
        )
