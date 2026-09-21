from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import cast, get_type_hints

from creator_provider.base import ImageProvider, LLMProvider, TTSProvider
from creator_provider.image.dalle_provider import DalleProvider
from creator_provider.llm.openai_provider import OpenAIProvider
from creator_provider.tts.openai_tts_provider import OpenAITTSProvider


def _assert_provider_contract(
    interface: type[object], implementation: type[object], method_name: str
) -> None:
    assert issubclass(implementation, interface)

    interface_method = cast(Callable[..., object], getattr(interface, method_name))
    implementation_method = cast(Callable[..., object], getattr(implementation, method_name))

    interface_signature = inspect.signature(interface_method)
    implementation_signature = inspect.signature(implementation_method)

    assert tuple(interface_signature.parameters.keys()) == tuple(
        implementation_signature.parameters.keys()
    )

    interface_hints = get_type_hints(interface_method)
    implementation_hints = get_type_hints(implementation_method)
    assert implementation_hints == interface_hints


def test_openai_provider_matches_llm_contract() -> None:
    _assert_provider_contract(LLMProvider, OpenAIProvider, "generate")


def test_dalle_provider_matches_image_contract() -> None:
    _assert_provider_contract(ImageProvider, DalleProvider, "generate")


def test_openai_tts_provider_matches_tts_contract() -> None:
    _assert_provider_contract(TTSProvider, OpenAITTSProvider, "generate")
