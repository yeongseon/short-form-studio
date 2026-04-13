from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

import httpx

from creator_provider.base import ImageProvider, ImageResult


class SDLocalProvider(ImageProvider):
    # Quality keywords prepended to all prompts to improve SD 1.5 output.
    _QUALITY_PREFIX = (
        "masterpiece, best quality, highly detailed, "
        "sharp focus, professional, 8k uhd"
    )

    # Only these keys from caller-provided params are forwarded to the
    # AUTOMATIC1111 /sdapi/v1/txt2img endpoint.  This allowlist prevents
    # injection of dangerous keys like `prompt`, `alwayson_scripts`,
    # `script_args`, or `override_settings`.
    _ALLOWED_API_KEYS = frozenset({
        "steps", "cfg_scale", "sampler_name", "negative_prompt", "seed",
    })

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

        # Merge caller-provided params — only allowlisted keys are forwarded
        # to AUTOMATIC1111.  This blocks injection of `prompt`,
        # `alwayson_scripts`, `override_settings`, etc.
        for key in self._ALLOWED_API_KEYS:
            if key in merged_params:
                payload[key] = merged_params[key]

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
