from __future__ import annotations

import base64
from pathlib import Path
import tempfile
from typing import Any

import httpx

from creator_provider.base import ImageProvider, ImageResult


class SDLocalProvider(ImageProvider):
    # Quality keywords prepended to all prompts to improve SD 1.5 output.
    _QUALITY_PREFIX = (
        "masterpiece, best quality, highly detailed, "
        "sharp focus, professional, 8k uhd"
    )

    # Keys that are internal to the pipeline and should NOT be sent to
    # the AUTOMATIC1111 /sdapi/v1/txt2img endpoint.
    _INTERNAL_KEYS = frozenset({"output_path", "width", "height"})

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        merged_params: dict[str, Any] = dict(params or {})
        width = int(merged_params.get("width", 512))
        height = int(merged_params.get("height", 768))

        # Auto-prepend quality keywords unless the caller explicitly
        # passed skip_quality_prefix=True.
        skip_prefix = merged_params.pop("skip_quality_prefix", False)
        effective_prompt = (
            prompt if skip_prefix else f"{self._QUALITY_PREFIX}, {prompt}"
        )

        payload: dict[str, Any] = {
            "prompt": effective_prompt,
            "width": width,
            "height": height,
            "steps": 25,
            "cfg_scale": 7,
            "sampler_name": "DPM++ 2M Karras",
        }

        # Merge caller-provided params (from registry defaults + per-request
        # overrides).  Strip internal keys that the SD API doesn't understand.
        api_params = {
            k: v for k, v in merged_params.items() if k not in self._INTERNAL_KEYS
        }
        payload.update(api_params)

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
