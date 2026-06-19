"""Image provider that wraps the god-tibo-imagen (gti) Python SDK.

Uses the private ChatGPT Codex backend for image generation.
Auth is file-based (~/.codex/auth.json + ~/.codex/installation_id).

WARNING: This provider calls an unsupported private endpoint that may break
without notice.
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import tempfile
from pathlib import Path
from typing import Any

from creator_provider.base import ImageProvider, ImageResult
from creator_provider.exceptions import ProviderAuthError, ProviderError, ProviderTimeoutError
from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS, validate_prompt_length

logger = logging.getLogger(__name__)

# PNG IHDR chunk starts at byte 16: width(4) + height(4)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _read_png_dimensions(path: Path) -> tuple[int, int]:
    """Read width and height from a PNG file's IHDR chunk."""
    with open(path, "rb") as f:
        sig = f.read(8)
        if sig != _PNG_SIGNATURE:
            return 0, 0
        # Skip chunk length (4 bytes) + chunk type 'IHDR' (4 bytes)
        f.read(8)
        width = struct.unpack(">I", f.read(4))[0]
        height = struct.unpack(">I", f.read(4))[0]
    return width, height


class CodexProvider(ImageProvider):
    """Image provider using the private ChatGPT Codex backend via gti SDK.

    Constructor signature matches the registry pattern: (endpoint, model_key).
    The endpoint parameter is ignored since gti manages its own endpoint internally.
    """

    def __init__(self, endpoint: str, model_key: str):
        self._endpoint = endpoint  # ignored — gti uses its own endpoint
        self.model_key = model_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        validate_prompt_length(prompt, MAX_IMAGE_PROMPT_CHARS, "Codex Image")

        merged = dict(params or {})

        # Warn if size params are passed — Codex decides dimensions itself
        width_req = merged.pop("width", None)
        height_req = merged.pop("height", None)
        if width_req is not None or height_req is not None:
            logger.warning(
                "CodexProvider: width/height params ignored — "
                "the Codex model decides output dimensions automatically."
            )

        output_path_str = merged.pop("output_path", None)
        if output_path_str:
            from importlib import import_module

            artifact_root = os.getenv("ARTIFACT_ROOT")
            validated = import_module("creator_domain.sanitize").validate_artifact_path(
                str(output_path_str),
                artifact_root or "data/artifacts",
            )
            output_path = str(validated)
        else:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                output_path = tmp.name

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Optional overrides from params
        gti_overrides: dict[str, Any] = {}
        if codex_home := merged.pop("codex_home", None):
            gti_overrides["codexHome"] = codex_home
        if model_override := merged.pop("model", None):
            gti_overrides["defaultModel"] = model_override

        # Size hint (e.g. "1024x1024") — pass through to gti even though
        # the backend may ignore it
        size = merged.pop("size", None)

        try:
            result = await asyncio.to_thread(
                self._generate_sync,
                prompt=prompt,
                output_path=output_path,
                size=size,
                overrides=gti_overrides,
            )
        except Exception as exc:
            error_msg = str(exc)
            if "UNAUTHORIZED" in error_msg or "401" in error_msg:
                raise ProviderAuthError(
                    "Codex auth expired. Re-login at https://chatgpt.com and refresh ~/.codex/auth.json"
                ) from exc
            if "timeout" in error_msg.lower() or "connect" in error_msg.lower():
                raise ProviderTimeoutError(f"Codex backend request failed: {error_msg}") from exc
            raise ProviderError(
                f"Codex image generation failed: {error_msg}. "
                "Note: This provider uses an unsupported private API that may be unavailable."
            ) from exc

        # Read actual dimensions from generated PNG
        saved = Path(result["savedPath"])
        width, height = _read_png_dimensions(saved)

        return ImageResult(
            image_path=str(saved),
            width=width,
            height=height,
            model_key=self.model_key,
            metadata={
                "provider": "codex",
                "response_id": result.get("responseId"),
                "session_id": result.get("sessionId"),
                "revised_prompt": result.get("revisedPrompt"),
                "warnings": result.get("warnings", []),
            },
        )

    @staticmethod
    def _generate_sync(
        *,
        prompt: str,
        output_path: str,
        size: str | None,
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        """Run gti synchronous generation in a thread."""
        from gti.client import Client

        client = Client(**overrides)
        result = client.generate_image(
            prompt=prompt,
            output_path=output_path,
            size=size,
        )
        return {
            "savedPath": result.saved_path,
            "responseId": result.response_id,
            "sessionId": result.session_id,
            "revisedPrompt": result.revised_prompt,
            "warnings": result.warnings,
        }
