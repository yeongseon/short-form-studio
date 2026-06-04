"""Groq SVG image provider — generates images via LLM SVG art + cairosvg rendering.

Uses Groq's fast LLM inference to generate SVG illustrations, then converts
to PNG using cairosvg. Produces dark, cinematic, emotional art suitable for
Korean storytelling Shorts (썰쇼츠).

No GPU required. Only needs GROQ_API_KEY and cairosvg.
"""

from __future__ import annotations

import logging
import os
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderError
from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS, validate_prompt_length

logger = logging.getLogger(__name__)

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_DEFAULT_WIDTH = 1080
_DEFAULT_HEIGHT = 1920
_MAX_WIDTH = 2048
_MAX_HEIGHT = 2048
_MIN_DIM = 64

_SVG_SYSTEM_PROMPT = (
    "You are an SVG illustration artist. Output ONLY raw SVG code. "
    "No markdown backticks, no explanation, no comments outside SVG. "
    "Create dark, cinematic, emotional illustrations using gradients, silhouettes, "
    "and muted colors (dark blues, blacks, subtle golds/warm highlights). "
    'The SVG must have viewBox="0 0 {width} {height}". '
    "Use defs for gradients. Keep shapes simple but evocative. "
    "Style: Korean traditional art meets modern cinematic mood."
)


class GroqSvgImageProvider(ImageProvider):
    """Generates images by having Groq LLM produce SVG, then rasterizing to PNG."""

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint
        self.model_key = model_key
        self._api_key = os.getenv("GROQ_API_KEY", "")

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        validate_prompt_length(prompt, MAX_IMAGE_PROMPT_CHARS, "Image")

        if not self._api_key:
            raise ProviderError("GROQ_API_KEY not set")

        merged = dict(params or {})
        width = max(_MIN_DIM, min(int(merged.get("width", _DEFAULT_WIDTH)), _MAX_WIDTH))
        height = max(_MIN_DIM, min(int(merged.get("height", _DEFAULT_HEIGHT)), _MAX_HEIGHT))

        # Generate SVG via Groq
        svg_content = await self._generate_svg(prompt, width, height)

        # Convert SVG to PNG
        try:
            import cairosvg
        except ImportError as exc:
            raise ProviderError("cairosvg not installed: pip install cairosvg") from exc

        png_bytes = cairosvg.svg2png(
            bytestring=svg_content.encode("utf-8"),
            output_width=width,
            output_height=height,
        )

        # Write output
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
        output_path.write_bytes(png_bytes)

        return ImageResult(
            image_path=str(output_path), width=width, height=height, model_key=self.model_key
        )

    async def _generate_svg(self, prompt: str, width: int, height: int) -> str:
        """Call Groq LLM to generate SVG content with exponential backoff."""
        import asyncio

        system_prompt = _SVG_SYSTEM_PROMPT.format(width=width, height=height)
        max_retries = 5

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(max_retries):
                resp = await client.post(
                    _GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.8,
                        "max_tokens": 4000,
                    },
                )

                if resp.status_code == 429:
                    # Exponential backoff: 10s, 20s, 40s, 60s, 60s
                    wait_time = min(10 * (2 ** attempt), 60)
                    logger.warning(
                        "Groq rate limited, waiting %ds (attempt %d/%d)",
                        wait_time, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    raise ProviderError(f"Groq API error: {resp.status_code} {resp.text[:200]}")

                data = resp.json()
                if "error" in data:
                    raise ProviderError(f"Groq error: {data['error']}")

                svg = data["choices"][0]["message"]["content"]
                return self._clean_svg(svg)

        raise ProviderError(f"Groq rate limited after {max_retries} retries")

    @staticmethod
    def _clean_svg(raw: str) -> str:
        """Strip markdown fencing and extract pure SVG."""
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else parts[0]
            if raw.startswith("svg") or raw.startswith("xml"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw

        # Find the SVG start
        if not raw.strip().startswith("<"):
            idx = raw.find("<")
            if idx >= 0:
                raw = raw[idx:]

        if "<svg" not in raw:
            raise ProviderError("Groq did not produce valid SVG")

        return raw.strip()
