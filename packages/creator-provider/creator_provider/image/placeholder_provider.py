"""Placeholder image provider that generates solid-color PNGs locally.

Used for E2E testing when no external image generation API is available.
No network calls, no API keys — just generates a valid PNG with the prompt
text rendered as metadata.
"""

from __future__ import annotations

import os
import struct
import tempfile
import zlib
from importlib import import_module
from pathlib import Path
from typing import Any

from creator_provider.base import ImageProvider, ImageResult
from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS, validate_prompt_length


def _create_solid_png(width: int, height: int, r: int = 64, g: int = 128, b: int = 200) -> bytes:
    """Create a minimal valid PNG with a solid color (no PIL dependency)."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    # Raw image data: filter byte (0) + RGB pixels per row
    raw_row = b"\x00" + bytes([r, g, b]) * width
    raw_data = raw_row * height
    idat = _chunk(b"IDAT", zlib.compress(raw_data))
    iend = _chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


class PlaceholderImageProvider(ImageProvider):
    """Generates solid-color placeholder PNGs locally for testing."""

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint
        self.model_key = model_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        validate_prompt_length(prompt, MAX_IMAGE_PROMPT_CHARS, "Image")
        merged = dict(params or {})
        width = max(1, min(int(merged.get("width", 1024)), 4096))
        height = max(1, min(int(merged.get("height", 1792)), 4096))

        # Generate a deterministic color from the prompt (hashlib for consistency across runs)
        import hashlib
        h = int(hashlib.md5(prompt.encode(), usedforsecurity=False).hexdigest()[:6], 16)
        r, g, b = (h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF
        # Ensure minimum brightness
        r, g, b = max(r, 40), max(g, 40), max(b, 40)

        image_bytes = _create_solid_png(width, height, r, g, b)

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
        output_path.write_bytes(image_bytes)

        return ImageResult(image_path=str(output_path), width=width, height=height, model_key=self.model_key)
