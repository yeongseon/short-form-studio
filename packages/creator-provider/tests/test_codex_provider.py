"""Tests for CodexProvider (god-tibo-imagen integration)."""

from __future__ import annotations

import os
import struct
from pathlib import Path
from unittest import mock

import pytest
from creator_provider.exceptions import ProviderAuthError, ProviderError, ProviderTimeoutError
from creator_provider.image.codex_provider import CodexProvider, _read_png_dimensions


# Minimal valid PNG file (1x1 pixel, white)
def _make_png(width: int = 100, height: int = 200) -> bytes:
    """Create a minimal valid PNG with given dimensions."""
    signature = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: width(4) + height(4) + bit_depth(1) + color_type(1) + compression(1) + filter(1) + interlace(1)
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    import zlib

    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr_chunk = (
        struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    )
    # Minimal IDAT + IEND
    idat_data = zlib.compress(b"\x00" * (width * 3 + 1) * height)
    idat_crc = zlib.crc32(b"IDAT" + idat_data) & 0xFFFFFFFF
    idat_chunk = (
        struct.pack(">I", len(idat_data)) + b"IDAT" + idat_data + struct.pack(">I", idat_crc)
    )
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return signature + ihdr_chunk + idat_chunk + iend_chunk


class TestCodexProviderInit:
    def test_constructor_sets_model_key(self):
        provider = CodexProvider(
            endpoint="https://chatgpt.com/backend-api/codex", model_key="codex-gpt-image"
        )
        assert provider.model_key == "codex-gpt-image"

    def test_endpoint_is_stored_but_unused(self):
        provider = CodexProvider(endpoint="http://ignored.example.com", model_key="codex-gpt-image")
        assert provider._endpoint == "http://ignored.example.com"


class TestReadPngDimensions:
    def test_valid_png(self, tmp_path: Path):
        png_file = tmp_path / "test.png"
        png_file.write_bytes(_make_png(1536, 1024))
        w, h = _read_png_dimensions(png_file)
        assert w == 1536
        assert h == 1024

    def test_invalid_file_returns_zeros(self, tmp_path: Path):
        bad_file = tmp_path / "bad.png"
        bad_file.write_bytes(b"not a png file")
        w, h = _read_png_dimensions(bad_file)
        assert w == 0
        assert h == 0


class TestCodexProviderGenerate:
    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path: Path):
        output_file = tmp_path / "output.png"
        png_bytes = _make_png(1254, 1254)

        def fake_generate_sync(*, prompt, output_path, size, overrides):
            Path(output_path).write_bytes(png_bytes)
            return {
                "savedPath": output_path,
                "responseId": "resp_123",
                "sessionId": "sess_456",
                "revisedPrompt": "a blue square",
                "warnings": [],
            }

        provider = CodexProvider(
            endpoint="https://chatgpt.com/backend-api/codex", model_key="codex-gpt-image"
        )

        with mock.patch.object(CodexProvider, "_generate_sync", side_effect=fake_generate_sync), \
                mock.patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            result = await provider.generate(
                "a blue square icon",
                {"output_path": str(output_file)},
            )

        assert result.image_path == str(output_file)
        assert result.width == 1254
        assert result.height == 1254
        assert result.model_key == "codex-gpt-image"
        assert result.metadata["provider"] == "codex"
        assert result.metadata["response_id"] == "resp_123"
        assert result.metadata["revised_prompt"] == "a blue square"

    @pytest.mark.asyncio
    async def test_generate_uses_temp_file_when_no_output_path(self, tmp_path: Path):
        png_bytes = _make_png(800, 600)

        def fake_generate_sync(*, prompt, output_path, size, overrides):
            Path(output_path).write_bytes(png_bytes)
            return {
                "savedPath": output_path,
                "responseId": "resp_789",
                "sessionId": "sess_012",
                "revisedPrompt": prompt,
                "warnings": [],
            }

        provider = CodexProvider(endpoint="unused", model_key="codex-gpt-image")

        with mock.patch.object(CodexProvider, "_generate_sync", side_effect=fake_generate_sync):
            result = await provider.generate("test prompt")

        assert Path(result.image_path).exists()
        assert result.width == 800
        assert result.height == 600

    @pytest.mark.asyncio
    async def test_width_height_params_ignored_with_warning(self, tmp_path: Path, caplog):
        png_bytes = _make_png(1536, 1024)

        def fake_generate_sync(*, prompt, output_path, size, overrides):
            Path(output_path).write_bytes(png_bytes)
            return {
                "savedPath": output_path,
                "responseId": "resp_abc",
                "sessionId": "sess_def",
                "revisedPrompt": prompt,
                "warnings": [],
            }

        provider = CodexProvider(endpoint="unused", model_key="codex-gpt-image")

        with mock.patch.object(CodexProvider, "_generate_sync", side_effect=fake_generate_sync):
            import logging

            with caplog.at_level(logging.WARNING):
                result = await provider.generate(
                    "test",
                    {"width": 1024, "height": 1792},
                )

        assert "ignored" in caplog.text.lower()
        # Actual dimensions come from the generated PNG, not from params
        assert result.width == 1536
        assert result.height == 1024


class TestCodexProviderErrors:
    @pytest.mark.asyncio
    async def test_auth_error_raises_provider_auth_error(self):
        provider = CodexProvider(endpoint="unused", model_key="codex-gpt-image")

        with mock.patch.object(
            CodexProvider,
            "_generate_sync",
            side_effect=RuntimeError("UNAUTHORIZED: token expired"),
        ), pytest.raises(ProviderAuthError, match="Codex auth expired"):
            await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_timeout_error(self):
        provider = CodexProvider(endpoint="unused", model_key="codex-gpt-image")

        with mock.patch.object(
            CodexProvider,
            "_generate_sync",
            side_effect=RuntimeError("Connect timeout exceeded"),
        ), pytest.raises(ProviderTimeoutError, match="Codex backend request failed"):
            await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generic_error_raises_provider_error(self):
        provider = CodexProvider(endpoint="unused", model_key="codex-gpt-image")

        with mock.patch.object(
            CodexProvider,
            "_generate_sync",
            side_effect=RuntimeError("Something unexpected"),
        ), pytest.raises(ProviderError, match="unsupported private API"):
            await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_prompt_too_long_raises_validation_error(self):
        from creator_provider.exceptions import ProviderValidationError

        provider = CodexProvider(endpoint="unused", model_key="codex-gpt-image")
        long_prompt = "x" * 3000

        with pytest.raises(ProviderValidationError, match="too long"):
            await provider.generate(long_prompt)


class TestCodexProviderRegistry:
    def test_codex_registered_in_default_registry(self):
        from creator_provider.registry import ProviderCategory, get_default_registry

        registry = get_default_registry()
        entry = registry.resolve("codex-gpt-image")
        assert entry.provider_type == "codex_image"
        assert entry.category == ProviderCategory.IMAGE
        assert entry.requires_gpu is False

    def test_codex_provider_instantiates_from_registry(self):
        from creator_provider.registry import get_default_registry

        registry = get_default_registry()
        provider = registry.get_provider("codex-gpt-image")
        assert isinstance(provider, CodexProvider)
        assert provider.model_key == "codex-gpt-image"
