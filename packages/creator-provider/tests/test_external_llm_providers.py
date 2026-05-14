from __future__ import annotations

import os
from unittest import mock

import httpx
import pytest

from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError


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
    async def test_generate_api_error_raises_provider_error(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(401, request=request)
        status_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(ProviderError),
            ):
                await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_timeout_raises_provider_timeout_error(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        timeout_error = httpx.TimeoutException("timeout", request=request)

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            with (
                mock.patch("httpx.AsyncClient.post", side_effect=timeout_error),
                pytest.raises(ProviderTimeoutError),
            ):
                await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_rate_limit_raises_rate_limit_error(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(429, request=request)
        status_error = httpx.HTTPStatusError(
            "Too Many Requests", request=request, response=response
        )

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(RateLimitError),
            ):
                await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_choices_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"choices": []}

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider(endpoint="https://api.openai.com", model_key="gpt-4o-mini")
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(ProviderError, match="no choices"),
            ):
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
    async def test_generate_api_error_raises_provider_error(self):
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
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(ProviderError),
            ):
                await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_timeout_raises_provider_timeout_error(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        timeout_error = httpx.TimeoutException("timeout", request=request)

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ak-test"}):
            from creator_provider.llm.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(
                endpoint="https://api.anthropic.com",
                model_key="claude-sonnet-4-20250514",
            )
            with (
                mock.patch("httpx.AsyncClient.post", side_effect=timeout_error),
                pytest.raises(ProviderTimeoutError),
            ):
                await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_rate_limit_raises_rate_limit_error(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        status_error = httpx.HTTPStatusError(
            "Too Many Requests", request=request, response=response
        )

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ak-test"}):
            from creator_provider.llm.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(
                endpoint="https://api.anthropic.com",
                model_key="claude-sonnet-4-20250514",
            )
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(RateLimitError),
            ):
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
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(ProviderError, match="no content blocks"),
            ):
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
    async def test_generate_api_error_raises_provider_error(self):
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
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(ProviderError),
            ):
                await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_timeout_raises_provider_timeout_error(self):
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        )
        timeout_error = httpx.TimeoutException("timeout", request=request)

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.llm.gemini_provider import GeminiProvider

            provider = GeminiProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="gemini-2.0-flash",
            )
            with (
                mock.patch("httpx.AsyncClient.post", side_effect=timeout_error),
                pytest.raises(ProviderTimeoutError),
            ):
                await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_rate_limit_raises_rate_limit_error(self):
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        )
        response = httpx.Response(429, request=request)
        status_error = httpx.HTTPStatusError(
            "Too Many Requests", request=request, response=response
        )

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}):
            from creator_provider.llm.gemini_provider import GeminiProvider

            provider = GeminiProvider(
                endpoint="https://generativelanguage.googleapis.com",
                model_key="gemini-2.0-flash",
            )
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(RateLimitError),
            ):
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
            with (
                mock.patch("httpx.AsyncClient.post", return_value=mock_response),
                pytest.raises(ProviderError, match="no candidates"),
            ):
                await provider.generate("test prompt")


class TestOllamaProvider:
    def test_constructor_sets_attributes(self):
        from creator_provider.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider("http://localhost:11434", "qwen3-4b")
        assert provider.endpoint == "http://localhost:11434"
        assert provider.model_name == "qwen3:4b"

    @pytest.mark.asyncio
    async def test_generate_success(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"message": {"content": "Hello"}}

        from creator_provider.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider("http://localhost:11434", "qwen3-4b")
        with mock.patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await provider.generate("test prompt")
            assert result == "Hello"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_provider_error(self):
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        response = httpx.Response(500, request=request)
        status_error = httpx.HTTPStatusError(
            "Internal Server Error", request=request, response=response
        )

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        from creator_provider.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider("http://localhost:11434", "qwen3-4b")
        with (
            mock.patch("httpx.AsyncClient.post", return_value=mock_response),
            pytest.raises(ProviderError),
        ):
            await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_timeout_raises_provider_timeout_error(self):
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        timeout_error = httpx.TimeoutException("timeout", request=request)

        from creator_provider.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider("http://localhost:11434", "qwen3-4b")
        with (
            mock.patch("httpx.AsyncClient.post", side_effect=timeout_error),
            pytest.raises(ProviderTimeoutError),
        ):
            await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_rate_limit_raises_rate_limit_error(self):
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        response = httpx.Response(429, request=request)
        status_error = httpx.HTTPStatusError(
            "Too Many Requests", request=request, response=response
        )

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        from creator_provider.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider("http://localhost:11434", "qwen3-4b")
        with (
            mock.patch("httpx.AsyncClient.post", return_value=mock_response),
            pytest.raises(RateLimitError),
        ):
            await provider.generate("test prompt")

    @pytest.mark.asyncio
    async def test_generate_empty_content_raises_provider_error(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.json.return_value = {"message": {"content": ""}}

        from creator_provider.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider("http://localhost:11434", "qwen3-4b")
        with (
            mock.patch("httpx.AsyncClient.post", return_value=mock_response),
            pytest.raises(ProviderError, match="empty content"),
        ):
            await provider.generate("test prompt")
