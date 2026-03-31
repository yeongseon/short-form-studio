from __future__ import annotations

import base64
from pathlib import Path
import tempfile
from typing import Any

import httpx

from creator_provider.base import ImageProvider, ImageResult


class SDLocalProvider(ImageProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        merged_params: dict[str, Any] = dict(params or {})
        width = int(merged_params.get("width", 512))
        height = int(merged_params.get("height", 768))

        payload: dict[str, Any] = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": 15,
            "cfg_scale": 7,
        }
        payload.update(merged_params)

        url = f"{self.endpoint}/sdapi/v1/txt2img"
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to connect to SD Local provider at {url}: {exc}") from exc

        data = response.json()
        image_base64 = str(data["images"][0]).split(",", 1)[-1]
        image_bytes = base64.b64decode(image_base64)

        requested_output = merged_params.get("output_path")
        if requested_output:
            output_path = Path(str(requested_output))
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
