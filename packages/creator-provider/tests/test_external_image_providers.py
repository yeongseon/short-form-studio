from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest import mock

import httpx
import pytest


class TestDalleProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.image.dalle_provider import DalleProvider

            provider = DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3")
            assert provider.endpoint == "https://api.openai.com"
            assert provider.model_key == "dall-e-3"
            assert provider.api_key == "sk-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.image.dalle_provider import DalleProvider

            with pytest.raises(ValueError, match="not configured"):
                DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3")

    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path: Path):
        image_bytes = b"dalle-image-bytes"
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"data": [{"b64_json": encoded}]}

        output_path = tmp_path / "nested" / "dalle.png"
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.image.dalle_provider import DalleProvider

            provider = DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
                result = await provider.generate(
                    "test prompt",
                    {"width": 640, "height": 960, "output_path": str(output_path)},
                )

        mock_post.assert_called_once()
        assert output_path.exists()
        assert output_path.read_bytes() == image_bytes
        assert result.image_path == str(output_path)
        assert result.width == 640
        assert result.height == 960
        assert result.model_key == "dall-e-3"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
        response = httpx.Response(401, request=request)
        status_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.image.dalle_provider import DalleProvider

            provider = DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="DALL-E API request failed"):
                    await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_response_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"data": []}

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.image.dalle_provider import DalleProvider

            provider = DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="no images"):
                    await provider.generate("test prompt")


class TestStabilityProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"STABILITY_API_KEY": "st-test"}):
            from creator_provider.image.stability_provider import StabilityProvider

            provider = StabilityProvider(
                endpoint="https://api.stability.ai",
                model_key="sd3-medium",
            )
            assert provider.endpoint == "https://api.stability.ai"
            assert provider.model_key == "sd3-medium"
            assert provider.api_key == "st-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.image.stability_provider import StabilityProvider

            with pytest.raises(ValueError, match="not configured"):
                StabilityProvider(endpoint="https://api.stability.ai", model_key="sd3-medium")

    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path: Path):
        image_bytes = b"stability-image-bytes"

        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.content = image_bytes

        output_path = tmp_path / "nested" / "stability.webp"
        with mock.patch.dict(os.environ, {"STABILITY_API_KEY": "st-test"}):
            from creator_provider.image.stability_provider import StabilityProvider

            provider = StabilityProvider(
                endpoint="https://api.stability.ai",
                model_key="sd3-medium",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
                result = await provider.generate(
                    "test prompt",
                    {
                        "aspect_ratio": "16:9",
                        "output_format": "webp",
                        "output_path": str(output_path),
                    },
                )

        mock_post.assert_called_once()
        assert output_path.exists()
        assert output_path.read_bytes() == image_bytes
        assert result.image_path == str(output_path)
        assert result.width == 1024
        assert result.height == 576
        assert result.model_key == "sd3-medium"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request("POST", "https://api.stability.ai/v2beta/stable-image/generate/sd3")
        response = httpx.Response(500, request=request)
        status_error = httpx.HTTPStatusError("Server error", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"STABILITY_API_KEY": "st-test"}):
            from creator_provider.image.stability_provider import StabilityProvider

            provider = StabilityProvider(
                endpoint="https://api.stability.ai",
                model_key="sd3-medium",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="Stability AI API request failed"):
                    await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_response_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.content = b""

        with mock.patch.dict(os.environ, {"STABILITY_API_KEY": "st-test"}):
            from creator_provider.image.stability_provider import StabilityProvider

            provider = StabilityProvider(
                endpoint="https://api.stability.ai",
                model_key="sd3-medium",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="empty response"):
                    await provider.generate("test prompt")


class TestImagenProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.image.imagen_provider import ImagenProvider

            provider = ImagenProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="imagen-3",
            )
            assert provider.endpoint == "https://generativelanguage.googleapis.com"
            assert provider.model_key == "imagen-3"
            assert provider.api_key == "gk-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.image.imagen_provider import ImagenProvider

            with pytest.raises(ValueError, match="not configured"):
                ImagenProvider(
                    endpoint="https://generativelanguage.googleapis.com",
                    model_key="imagen-3",
                )

    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path: Path):
        image_bytes = b"imagen-image-bytes"
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {
            "generatedImages": [{"image": {"imageBytes": encoded}}],
        }

        output_path = tmp_path / "nested" / "imagen.png"
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.image.imagen_provider import ImagenProvider

            provider = ImagenProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="imagen-3",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
                result = await provider.generate(
                    "test prompt",
                    {"width": 1024, "height": 1536, "output_path": str(output_path)},
                )

        mock_post.assert_called_once()
        assert output_path.exists()
        assert output_path.read_bytes() == image_bytes
        assert result.image_path == str(output_path)
        assert result.width == 1024
        assert result.height == 1536
        assert result.model_key == "imagen-3"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/imagen-3:generateImages",
        )
        response = httpx.Response(401, request=request)
        status_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.image.imagen_provider import ImagenProvider

            provider = ImagenProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="imagen-3",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="Imagen API request failed"):
                    await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_response_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"generatedImages": []}

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.image.imagen_provider import ImagenProvider

            provider = ImagenProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="imagen-3",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="no images"):
                    await provider.generate("test prompt")
