from __future__ import annotations

import asyncio

import pytest
from creator_provider.exceptions import ProviderValidationError

from creator_provider.validation import validate_prompt_length


def test_validate_prompt_length_raises_on_oversized_prompt() -> None:
    with pytest.raises(ProviderValidationError, match="prompt too long"):
        validate_prompt_length("x" * 11, 10, "LLM")


def test_validate_prompt_length_allows_valid_length_prompt() -> None:
    validate_prompt_length("x" * 10, 10, "LLM")


def test_all_llm_providers_call_validate_prompt_length() -> None:
    """Verify each LLM provider rejects oversized prompts via the shared validator."""
    from creator_provider.validation import MAX_LLM_PROMPT_CHARS
    from creator_provider.llm.openai_provider import OpenAIProvider
    from creator_provider.llm.anthropic_provider import AnthropicProvider
    from creator_provider.llm.gemini_provider import GeminiProvider
    from creator_provider.llm.ollama_provider import OllamaProvider

    oversized = "x" * (MAX_LLM_PROMPT_CHARS + 1)
    for ProviderCls in [OpenAIProvider, AnthropicProvider, GeminiProvider, OllamaProvider]:
        provider = ProviderCls.__new__(ProviderCls)
        with pytest.raises(ProviderValidationError, match="prompt too long"):
            asyncio.run(provider.generate(oversized))


def test_all_image_providers_call_validate_prompt_length() -> None:
    """Verify each image provider rejects oversized prompts via the shared validator."""
    from creator_provider.validation import MAX_IMAGE_PROMPT_CHARS
    from creator_provider.image.dalle_provider import DalleProvider
    from creator_provider.image.sd_local_provider import SDLocalProvider
    from creator_provider.image.stability_provider import StabilityProvider
    from creator_provider.image.imagen_provider import ImagenProvider

    oversized = "x" * (MAX_IMAGE_PROMPT_CHARS + 1)
    for ProviderCls in [DalleProvider, SDLocalProvider, StabilityProvider, ImagenProvider]:
        provider = ProviderCls.__new__(ProviderCls)
        with pytest.raises(ProviderValidationError, match="prompt too long"):
            asyncio.run(provider.generate(oversized))


def test_all_tts_providers_call_validate_prompt_length() -> None:
    """Verify each TTS provider rejects oversized text via the shared validator."""
    from creator_provider.validation import MAX_TTS_TEXT_CHARS
    from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider
    from creator_provider.tts.openai_tts_provider import OpenAITTSProvider
    from creator_provider.tts.piper_tts_provider import PiperTTSProvider
    from creator_provider.tts.qwen_tts_provider import QwenTTSProvider

    oversized = "x" * (MAX_TTS_TEXT_CHARS + 1)
    for ProviderCls in [ElevenLabsProvider, OpenAITTSProvider, PiperTTSProvider, QwenTTSProvider]:
        provider = ProviderCls.__new__(ProviderCls)
        with pytest.raises(ProviderValidationError, match="prompt too long"):
            asyncio.run(provider.generate(oversized))
