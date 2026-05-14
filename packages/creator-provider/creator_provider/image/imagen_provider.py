from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS, validate_prompt_length

# Map common width x height to Imagen API aspectRatio values.
_ASPECT_RATIOS: dict[tuple[int, int], str] = {
    (1024, 1792): "9:16",
    (1792, 1024): "16:9",
    (1024, 1024): "1:1",
    (768, 1024): "3:4",
    (1024, 768): "4:3",
}


def _resolve_aspect_ratio(width: int, height: int) -> str:
    """Derive the closest Imagen API aspectRatio string from width/height."""
    key = (width, height)
    if key in _ASPECT_RATIOS:
        return _ASPECT_RATIOS[key]
    # Fallback: compute ratio and pick the closest standard option.
    ratio = width / height
    if ratio < 0.65:
        return "9:16"
    elif ratio < 0.85:
        return "3:4"
    elif ratio < 1.18:
        return "1:1"
    elif ratio < 1.45:
        return "4:3"
    else:
        return "16:9"


class ImagenProvider(ImageProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key
        api_key = resolve_api_key("google")
        if api_key is None:
            raise ValueError("Google API key not configured")
        self.api_key = api_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        validate_prompt_length(prompt, MAX_IMAGE_PROMPT_CHARS, "Image")
        merged = dict(params or {})
        width = int(merged.get("width", 1024))
        height = int(merged.get("height", 1792))
        aspect_ratio = merged.get("aspect_ratio", _resolve_aspect_ratio(width, height))
        timeout = float(merged.get("timeout", 120.0))

        url = f"{self.endpoint}/v1beta/models/{self.model_key}:generateImages"
        payload = {
            "prompt": prompt,
            "config": {
                "numberOfImages": 1,
                "aspectRatio": aspect_ratio,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "Imagen API request failed") from exc

        data = response.json()
        images = data.get("generatedImages", [])
        if not images:
            raise ProviderError("Imagen API returned no images")

        image_b64 = images[0].get("image", {}).get("imageBytes", "")
        if not image_b64:
            raise ProviderError("Imagen API returned empty image data")

        image_bytes = base64.b64decode(image_b64)

        output_path_str = merged.get("output_path")
        if output_path_str:
            output_path = Path(str(output_path_str))
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
