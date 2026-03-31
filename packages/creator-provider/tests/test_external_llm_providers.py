from __future__ import annotations

import os
from unittest import mock

import httpx
import pytest


class TestOpenAIProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            assert provider.endpoint == "https://api.openai.com"
            assert provider.model_key == "gpt-4o-mini"
            assert provider.api_key == "sk-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.llm.openai_provider import OpenAIProvider

            with pytest.raises(ValueError, match="not configured"):
                OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")

    @pytest.mark.asyncio
    async def test_generate_success(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}],
        }

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
                result = await provider.generate("test prompt")
                assert result == "Hello world"
                mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(401, request=request)
        status_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="OpenAI API request failed"):
                    await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_choices_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"choices": []}

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="no choices"):
                    await provider.generate("test prompt")


class TestAnthropicProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ak-test"}):
            from creator_provider.llm.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(
                endpoint="https://api.anthropic.com",
                model_key="claude-sonnet-4-20250514",
            )
            assert provider.endpoint == "https://api.anthropic.com"
            assert provider.model_key == "claude-sonnet-4-20250514"
            assert provider.api_key == "ak-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.llm.anthropic_provider import AnthropicProvider

            with pytest.raises(ValueError, match="not configured"):
                AnthropicProvider(
                    endpoint="https://api.anthropic.com",
                    model_key="claude-sonnet-4-20250514",
                )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Claude"}],
        }

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ak-test"}):
            from creator_provider.llm.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(
                endpoint="https://api.anthropic.com",
                model_key="claude-sonnet-4-20250514",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                result = await provider.generate("test prompt")
                assert result == "Hello from Claude"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(401, request=request)
        status_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ak-test"}):
            from creator_provider.llm.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(
                endpoint="https://api.anthropic.com",
                model_key="claude-sonnet-4-20250514",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="Anthropic API request failed"):
                    await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_content_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"content": []}

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ak-test"}):
            from creator_provider.llm.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(
                endpoint="https://api.anthropic.com",
                model_key="claude-sonnet-4-20250514",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="no content blocks"):
                    await provider.generate("test prompt")


class TestGeminiProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.llm.gemini_provider import GeminiProvider

            provider = GeminiProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="gemini-2.0-flash",
            )
            assert provider.endpoint == "https://generativelanguage.googleapis.com"
            assert provider.model_key == "gemini-2.0-flash"
            assert provider.api_key == "gk-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.llm.gemini_provider import GeminiProvider

            with pytest.raises(ValueError, match="not configured"):
                GeminiProvider(
                    endpoint="https://generativelanguage.googleapis.com",
                    model_key="gemini-2.0-flash",
                )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}],
        }

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.llm.gemini_provider import GeminiProvider

            provider = GeminiProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="gemini-2.0-flash",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                result = await provider.generate("test prompt")
                assert result == "Hello from Gemini"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        )
        response = httpx.Response(401, request=request)
        status_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.llm.gemini_provider import GeminiProvider

            provider = GeminiProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="gemini-2.0-flash",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="Gemini API request failed"):
                    await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_no_candidates_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"candidates": []}

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.llm.gemini_provider import GeminiProvider

            provider = GeminiProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="gemini-2.0-flash",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
                with pytest.raises(RuntimeError, match="no candidates"):
                    await provider.generate("test prompt")
