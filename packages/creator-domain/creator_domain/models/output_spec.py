from __future__ import annotations

import sys
from enum import Enum
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

if sys.version_info >= (3, 11):  # noqa: UP036
    from enum import StrEnum
else:

    class StrEnum(str, Enum):  # noqa: UP042
        def __str__(self) -> str:
            return self.value


class AspectRatio(StrEnum):
    VERTICAL = "9:16"
    SQUARE = "1:1"
    LANDSCAPE = "16:9"
    OTHER = "other"


class VideoCodec(StrEnum):
    H264 = "libx264"
    H265 = "libx265"


class AudioCodec(StrEnum):
    AAC = "aac"
    MP3 = "libmp3lame"


class _RenderProfileLike(Protocol):
    width: int
    height: int
    fps: int
    crf: int
    preset: str
    video_codec: object
    audio_codec: object


def _aspect_ratio(width: int, height: int) -> AspectRatio:
    if width == height:
        return AspectRatio.SQUARE
    if width * 16 == height * 9:
        return AspectRatio.VERTICAL
    if width * 9 == height * 16:
        return AspectRatio.LANDSCAPE
    return AspectRatio.OTHER


class OutputSpec(BaseModel):
    """Output geometry only: dimensions and frame rate.

    Duration belongs to recipes/products and codecs to EncodingProfile, so this
    stays a generic geometry value object with a derived aspect ratio.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    fps: int = Field(ge=1)

    @property
    def aspect_ratio(self) -> AspectRatio:
        return _aspect_ratio(self.width, self.height)

    @classmethod
    def short_vertical(cls) -> OutputSpec:
        return cls(width=1080, height=1920, fps=30)

    @classmethod
    def short_square(cls) -> OutputSpec:
        return cls(width=1080, height=1080, fps=30)

    @classmethod
    def short_landscape(cls) -> OutputSpec:
        return cls(width=1920, height=1080, fps=30)

    @classmethod
    def preset(cls, name: str) -> OutputSpec:
        """Resolve a named short output preset (geometry only).

        Platform names (Shorts/Reels/TikTok) belong to the product layer; the
        core presets are geometry-only and platform-agnostic.
        """
        presets = {
            "short_vertical": cls.short_vertical,
            "short_square": cls.short_square,
            "short_landscape": cls.short_landscape,
        }
        factory = presets.get(name)
        if factory is None:
            raise ValueError(f"Unknown output preset: {name!r}")
        return factory()

    @classmethod
    def from_render_profile(cls, profile: _RenderProfileLike) -> OutputSpec:
        """Adapt a legacy RenderProfile's geometry into an OutputSpec.

        Uses attribute access (not import) so the domain package keeps zero
        dependency on creator-service where RenderProfile lives (ADR-001).
        """
        return cls(width=profile.width, height=profile.height, fps=profile.fps)


def _coerce_video_codec(value: object) -> VideoCodec:
    raw = getattr(value, "value", value)
    return VideoCodec(str(raw))


def _coerce_audio_codec(value: object) -> AudioCodec:
    raw = getattr(value, "value", value)
    return AudioCodec(str(raw))


class EncodingProfile(BaseModel):
    """Codec and quality settings, independent of output geometry.

    Selectable via the named presets ``preview``, ``standard``, and
    ``high_quality``.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str = Field(max_length=50)
    video_codec: VideoCodec = VideoCodec.H264
    audio_codec: AudioCodec = AudioCodec.AAC
    crf: int = Field(ge=0, le=51)
    preset: str = Field(max_length=50)

    @classmethod
    def preview(cls) -> EncodingProfile:
        return cls(name="preview", crf=28, preset="veryfast")

    @classmethod
    def standard(cls) -> EncodingProfile:
        return cls(name="standard", crf=23, preset="fast")

    @classmethod
    def high_quality(cls) -> EncodingProfile:
        return cls(name="high_quality", crf=18, preset="slow")

    @classmethod
    def by_name(cls, name: str) -> EncodingProfile:
        presets = {
            "preview": cls.preview,
            "standard": cls.standard,
            "high_quality": cls.high_quality,
        }
        factory = presets.get(name)
        if factory is None:
            raise ValueError(f"Unknown encoding profile: {name!r}")
        return factory()

    @classmethod
    def from_render_profile(cls, profile: _RenderProfileLike) -> EncodingProfile:
        """Adapt a legacy RenderProfile's codec/quality into an EncodingProfile."""
        return cls(
            name="standard",
            video_codec=_coerce_video_codec(profile.video_codec),
            audio_codec=_coerce_audio_codec(profile.audio_codec),
            crf=profile.crf,
            preset=profile.preset,
        )
