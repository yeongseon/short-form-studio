"""Groq SVG image provider — generates images via LLM SVG art + cairosvg rendering.

Uses Groq's fast LLM inference to generate SVG illustrations, then converts
to PNG using cairosvg. Produces dark, cinematic, emotional art suitable for
Korean storytelling Shorts (썰쇼츠).

Includes XML repair and retry logic to handle common LLM SVG generation errors
(namespace prefixes, duplicate attributes, malformed XML).

No GPU required. Only needs GROQ_API_KEY and cairosvg.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderError
from creator_provider.image.svg_repair import deduplicate_attrs, repair_svg_xml
from creator_provider.image.svg_safety import finalize_svg, parse_svg, strip_svg_markup
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
    "Style: Korean traditional art meets modern cinematic mood. "
    "CRITICAL RULES: "
    "1) Use ONLY standard SVG elements and attributes. "
    "2) Do NOT use namespace prefixes like xlink: — use plain 'href' instead of 'xlink:href'. "
    "3) Do NOT duplicate any attribute on the same element. "
    "4) Do NOT use xml:space or other xml: prefixed attributes. "
    '5) Start with <svg xmlns="http://www.w3.org/2000/svg" ...> — no other xmlns declarations needed. '
    "6) Ensure all tags are properly closed."
)

_SVG_GENERATION_MAX_RETRIES = 3


def _deny_svg_resource(url: str, resource_type: str) -> bytes:
    raise ProviderError("SVG resource loading is disabled")


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

        # Generate valid SVG with repair and retry
        svg_content = await self._generate_valid_svg(prompt, width, height)

        # Convert SVG to PNG
        try:
            import cairosvg
        except ImportError as exc:
            raise ProviderError("cairosvg not installed: pip install cairosvg") from exc

        png_bytes = cairosvg.surface.PNGSurface.convert(
            bytestring=svg_content.encode("utf-8"),
            output_width=width,
            output_height=height,
            # The surface API forwards this per-render callback to every resource loader.
            unsafe=False,
            url_fetcher=_deny_svg_resource,
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

    async def _generate_valid_svg(self, prompt: str, width: int, height: int) -> str:
        """Generate SVG with repair and retry logic.

        Attempts up to _SVG_GENERATION_MAX_RETRIES times. Each attempt:
        1. Calls Groq LLM to generate SVG
        2. Cleans markdown fencing
        3. Repairs common XML issues (namespace prefixes, duplicate attrs)
        4. Validates with xml.etree.ElementTree
        5. If validation fails, retries with error hint in prompt
        """
        last_error: str = ""

        for attempt in range(_SVG_GENERATION_MAX_RETRIES):
            # Add error hint for retry attempts
            effective_prompt = prompt
            if attempt > 0 and last_error:
                effective_prompt = (
                    f"{prompt}\n\n"
                    f"IMPORTANT: Your previous SVG had this XML error: {last_error}\n"
                    f"Fix this issue. Do NOT use namespace prefixes (xlink:, xml:). "
                    f"Do NOT duplicate attributes. Ensure valid XML."
                )

            raw_svg = await self._call_groq_llm(effective_prompt, width, height)
            cleaned_svg = self._clean_svg(raw_svg)
            repaired_svg = self._repair_svg_xml(cleaned_svg)

            sanitized_svg = self._sanitize_svg(repaired_svg)

            try:
                self._validate_svg_xml(sanitized_svg)
                logger.info(
                    "SVG validation passed on attempt %d/%d",
                    attempt + 1,
                    _SVG_GENERATION_MAX_RETRIES,
                )
                return finalize_svg(sanitized_svg)
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "SVG validation failed on attempt %d/%d: %s",
                    attempt + 1,
                    _SVG_GENERATION_MAX_RETRIES,
                    last_error,
                )

        # Final attempt: try to force-fix by stripping problematic elements
        logger.warning(
            "All SVG generation attempts failed. Using last repaired SVG with force cleanup."
        )
        final_svg = self._sanitize_svg(self._force_cleanup_svg(repaired_svg, width, height))
        self._validate_svg_xml(final_svg)
        return finalize_svg(final_svg)

    async def _call_groq_llm(self, prompt: str, width: int, height: int) -> str:
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
                        "temperature": 0.7,
                        "max_tokens": 4000,
                    },
                )

                if resp.status_code == 429:
                    # Exponential backoff: 10s, 20s, 40s, 60s, 60s
                    wait_time = min(10 * (2**attempt), 60)
                    logger.warning(
                        "Groq rate limited, waiting %ds (attempt %d/%d)",
                        wait_time,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    raise ProviderError(f"Groq API error: {resp.status_code} {resp.text[:200]}")

                data = resp.json()
                if "error" in data:
                    raise ProviderError(f"Groq error: {data['error']}")

                svg = data["choices"][0]["message"]["content"]
                return svg

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

    _repair_svg_xml = staticmethod(repair_svg_xml)
    _deduplicate_attrs = staticmethod(deduplicate_attrs)

    @staticmethod
    def _validate_svg_xml(svg: str) -> None:
        """Validate SVG as well-formed XML using ElementTree.

        Raises Exception if SVG is not valid XML.
        """
        try:
            parse_svg(svg)
        except ET.ParseError as exc:
            raise ValueError(f"SVG XML parse error: {exc}") from exc

    _sanitize_svg = staticmethod(strip_svg_markup)

    @staticmethod
    def _force_cleanup_svg(svg: str, width: int, height: int) -> str:
        """Last-resort cleanup: create a minimal valid SVG wrapper if parsing still fails.

        Tries to extract individual SVG elements and wrap them in a clean SVG root.
        If that also fails, returns a solid-color fallback SVG.
        """
        # Try one more parse after aggressive cleanup
        aggressive = svg
        # Remove all namespace-prefixed attributes
        aggressive = re.sub(r'\s+\w+:\w+="[^"]*"', "", aggressive)
        # Remove processing instructions
        aggressive = re.sub(r"<\?[^?]*\?>", "", aggressive)

        try:
            parse_svg(aggressive)
            return aggressive
        except ET.ParseError:
            pass

        # Extract content between <svg...> and </svg>
        inner_match = re.search(r"<svg[^>]*>(.*)</svg>", aggressive, re.DOTALL)
        if inner_match:
            inner = inner_match.group(1)
            fallback = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
                f"{inner}</svg>"
            )
            try:
                parse_svg(fallback)
                return fallback
            except ET.ParseError:
                pass

        # Ultimate fallback: dark gradient background
        logger.error("All SVG repair attempts failed. Using fallback gradient SVG.")
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="#1a1a2e"/>'
            f'<stop offset="100%" stop-color="#16213e"/>'
            f"</linearGradient></defs>"
            f'<rect width="{width}" height="{height}" fill="url(#bg)"/>'
            f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'fill="#c4a747" font-size="72" font-family="sans-serif">&#x2728;</text>'
            f"</svg>"
        )
