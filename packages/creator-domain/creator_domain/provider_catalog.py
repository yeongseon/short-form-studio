"""Catalog values and read ports independent of provider implementations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from pydantic import JsonValue


class ProviderCategory(Enum):
    LLM = "llm"
    IMAGE = "image"
    TTS = "tts"
    STT = "stt"


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    model_key: str
    provider_type: str
    endpoint: str
    category: ProviderCategory
    requires_gpu: bool = True
    is_local: bool = True
    default_params: Mapping[str, JsonValue] | None = None


class ModelRegistry(Protocol):
    def list_models(self) -> Sequence[ModelCatalogEntry]: ...


class ModelResolver(Protocol):
    def resolve(self, model_key: str) -> ModelCatalogEntry: ...
