"""Tests for HuggingFace image provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from creator_provider.image.huggingface_provider import (
    HuggingFaceImageProvider,
    _DEFAULT_MODEL,
    _FALLBACK_MODEL,
    _MAX_HEIGHT,
    _MAX_WIDTH,
)
from creator_provider.exceptions import ProviderError


@pytest.fixture
def provider():
    return HuggingFaceImageProvider(
        endpoint="https://api-inference.huggingface.co", model_key="hf-flux-schnell"
    )


def _mock_import():
    """Patch import_module to skip artifact path validation."""
    return patch(
        "creator_provider.image.huggingface_provider.import_module",
        return_value=type("M", (), {"validate_artifact_path": staticmethod(lambda p, r: p)})(),
    )


@pytest.mark.asyncio
class TestModelPinning:
    """Ensure user params cannot override the HF model."""

    async def test_model_param_stripped(self, provider):
        params = {
            "model": "evil/malicious-model",
            "width": 512,
            "height": 512,
            "output_path": "/tmp/test.png",
        }
        with patch.object(provider, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            with _mock_import():
                await provider.generate("test prompt", params)
            mock_req.assert_called_once()
            assert mock_req.call_args[0][1] == _DEFAULT_MODEL


@pytest.mark.asyncio
class TestDimensionClamping:
    """Ensure dimensions are clamped to safe maximums."""

    async def test_width_clamped(self, provider):
        with patch.object(provider, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = b"\x89PNG" + b"\x00" * 100
            with _mock_import():
                result = await provider.generate(
                    "test", {"width": 9999, "height": 9999, "output_path": "/tmp/t.png"}
                )
            assert result.width <= _MAX_WIDTH
            assert result.height <= _MAX_HEIGHT

    async def test_normal_dimensions_pass_through(self, provider):
        with patch.object(provider, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = b"\x89PNG" + b"\x00" * 100
            with _mock_import():
                result = await provider.generate(
                    "test", {"width": 768, "height": 1344, "output_path": "/tmp/t.png"}
                )
            assert result.width == 768
            assert result.height == 1344


@pytest.mark.asyncio
class TestFallbackBehavior:
    """Test fallback to secondary model on failure."""

    async def test_fallback_on_primary_failure(self, provider):
        call_count = {"n": 0}

        async def mock_request(prompt, model, w, h):
            call_count["n"] += 1
            if model == _DEFAULT_MODEL:
                raise RuntimeError("primary failed")
            return b"\x89PNG" + b"\x00" * 100

        with patch.object(provider, "_make_request", side_effect=mock_request):
            with _mock_import():
                result = await provider.generate("test", {"output_path": "/tmp/t.png"})
        assert call_count["n"] == 2
        assert result.image_path == "/tmp/t.png"

    async def test_both_models_fail_raises_provider_error(self, provider):
        async def mock_request(prompt, model, w, h):
            raise RuntimeError(f"{model} failed")

        with patch.object(provider, "_make_request", side_effect=mock_request):
            with _mock_import():
                with pytest.raises(ProviderError, match="both models"):
                    await provider.generate("test", {"output_path": "/tmp/t.png"})


@pytest.mark.asyncio
class TestPromptValidation:
    """Test prompt length validation."""

    async def test_long_prompt_rejected(self, provider):
        from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS

        long_prompt = "x" * (MAX_IMAGE_PROMPT_CHARS + 1)
        with pytest.raises(Exception):
            await provider.generate(long_prompt, {"output_path": "/tmp/t.png"})


@pytest.mark.asyncio
class TestDimensionLowerBound:
    """Ensure zero/negative dimensions are clamped to minimum 64."""

    async def test_zero_dimensions_clamped(self, provider):
        with patch.object(provider, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = b"\x89PNG" + b"\x00" * 100
            with _mock_import():
                result = await provider.generate(
                    "test", {"width": 0, "height": 0, "output_path": "/tmp/t.png"}
                )
            assert result.width >= 64
            assert result.height >= 64

    async def test_negative_dimensions_clamped(self, provider):
        with patch.object(provider, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = b"\x89PNG" + b"\x00" * 100
            with _mock_import():
                result = await provider.generate(
                    "test", {"width": -100, "height": -50, "output_path": "/tmp/t.png"}
                )
            assert result.width >= 64
            assert result.height >= 64
