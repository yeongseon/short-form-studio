from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderError, map_httpx_error


class DalleProvider(ImageProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key
        self.api_key = resolve_api_key("openai")

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        merged = dict(params or {})
        width = int(merged.get("width", 1024))
        height = int(merged.get("height", 1792))
        size = f"{width}x{height}"
        timeout = float(merged.get("timeout", 120.0))

        payload = {
            "model": self.model_key,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }

        url = f"{self.endpoint}/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "DALL-E API request failed") from exc

        data = response.json()
        images = data.get("data", [])
        if not images:
            raise ProviderError("DALL-E API returned no images")

        image_b64 = images[0].get("b64_json", "")
        if not image_b64:
            raise ProviderError("DALL-E API returned empty image data")

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
