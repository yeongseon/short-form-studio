from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import ImageProvider, ImageResult


class StabilityProvider(ImageProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key
        self.api_key = resolve_api_key("stability")

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
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
            raise RuntimeError(f"Stability AI API request failed: {exc}") from exc

        image_bytes = response.content
        if not image_bytes:
            raise RuntimeError("Stability AI API returned empty response")

        output_path_str = merged.get("output_path")
        if output_path_str:
            output_path = Path(str(output_path_str))
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
        )

    @staticmethod
    def _parse_aspect_ratio(ratio: str) -> tuple[int, int]:
        ratio_map = {
            "9:16": (576, 1024),
            "16:9": (1024, 576),
            "1:1": (1024, 1024),
            "3:2": (1024, 683),
            "2:3": (683, 1024),
        }
        return ratio_map.get(ratio, (1024, 1024))
