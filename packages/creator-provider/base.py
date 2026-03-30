from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ImageResult:
    image_path: str
    width: int
    height: int
    model_key: str
    metadata: dict[str, Any] | None = None


@dataclass
class AudioResult:
    audio_path: str
    duration_seconds: float
    model_key: str
    metadata: dict[str, Any] | None = None


@dataclass
class SubtitleResult:
    segments: list[dict[str, Any]]
    full_text: str
    model_key: str
    metadata: dict[str, Any] | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        ...


class ImageProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> ImageResult:
        ...


class TTSProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        text: str,
        voice: str = "default",
        params: dict[str, Any] | None = None,
    ) -> AudioResult:
        ...


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        params: dict[str, Any] | None = None,
    ) -> SubtitleResult:
        ...
