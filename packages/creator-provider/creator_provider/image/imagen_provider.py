from __future__ import annotations

import base64
from pathlib import Path
import tempfile
from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import ImageProvider, ImageResult


class ImagenProvider(ImageProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key
        self.api_key = resolve_api_key("google")

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        merged = dict(params or {})
        width = int(merged.get("width", 1024))
        height = int(merged.get("height", 1792))
        timeout = float(merged.get("timeout", 120.0))

        url = (
            f"{self.endpoint}/v1beta/models/{self.model_key}"
            f":generateImages?key={self.api_key}"
        )
        payload = {
            "prompt": prompt,
            "config": {
                "numberOfImages": 1,
            },
        }
        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Imagen API request failed: {exc}") from exc

        data = response.json()
        images = data.get("generatedImages", [])
        if not images:
            raise RuntimeError("Imagen API returned no images")

        image_b64 = images[0].get("image", {}).get("imageBytes", "")
        if not image_b64:
            raise RuntimeError("Imagen API returned empty image data")

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
