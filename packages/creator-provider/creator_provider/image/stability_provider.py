from __future__ import annotations

import os
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS, validate_prompt_length
from creator_provider.versioned_assets import get_loaded_asset_versions, get_schema


class StabilityProvider(ImageProvider):
    _ASPECT_RATIO_MAP = get_schema("stability_aspect_ratio_map")

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key
        self.api_key = resolve_api_key("stability")

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        validate_prompt_length(prompt, MAX_IMAGE_PROMPT_CHARS, "Image")
        merged = dict(params or {})
        aspect_ratio = str(merged.get("aspect_ratio", "9:16"))
        output_format = str(merged.get("output_format", "png"))
        timeout = float(merged.get("timeout", 120.0))

        width, height = self._parse_aspect_ratio(aspect_ratio)

        url = f"{self.endpoint}/v2beta/stable-image/generate/sd3"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "image/*",
        }

        form_data = {
            "prompt": prompt,
            "output_format": output_format,
            "aspect_ratio": aspect_ratio,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, data=form_data, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "Stability AI API request failed") from exc

        image_bytes = response.content
        if not image_bytes:
            raise ProviderError("Stability AI API returned empty response")

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
            with tempfile.NamedTemporaryFile(suffix=f".{output_format}", delete=False) as tmp:
                output_path = Path(tmp.name)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)

        return ImageResult(
            image_path=str(output_path),
            width=width,
            height=height,
            model_key=self.model_key,
            metadata={"asset_versions": get_loaded_asset_versions()},
        )

    @staticmethod
    def _parse_aspect_ratio(ratio: str) -> tuple[int, int]:
        dims = StabilityProvider._ASPECT_RATIO_MAP.get(ratio)
        if not isinstance(dims, list) or len(dims) != 2:
            return (1024, 1024)
        return (int(dims[0]), int(dims[1]))
