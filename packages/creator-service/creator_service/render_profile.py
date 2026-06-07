from dataclasses import dataclass
from enum import Enum


class Codec(Enum):
    H264 = "libx264"
    H265 = "libx265"


class AudioCodec(Enum):
    AAC = "aac"
    MP3 = "libmp3lame"


class TransitionStyle(Enum):
    CUT = "cut"
    FADE = "fade"
    KEN_BURNS = "ken_burns"


@dataclass
class RenderProfile:
    name: str = "shorts_default"
    width: int = 1080
    height: int = 1920  # 9:16 vertical
    fps: int = 30
    video_codec: Codec = Codec.H264
    audio_codec: AudioCodec = AudioCodec.AAC
    transition_style: TransitionStyle = TransitionStyle.FADE  # FADE default: KEN_BURNS too slow for single-CPU containers
    min_duration_seconds: int = 15
    max_duration_seconds: int = 60
    crf: int = 20  # quality (lower = better, 18-28 typical)
    preset: str = "fast"  # fast: good quality/memory balance for containers (medium OOMs with 5+ scenes)
    burn_subtitles: bool = True
    subtitle_font_size: int = 48  # scaled for 1080p mobile readability

    @classmethod
    def default(cls) -> "RenderProfile":
        return cls()

    @classmethod
    def high_quality(cls) -> "RenderProfile":
        return cls(name="high_quality", crf=18, preset="slow")

    @classmethod
    def fast_preview(cls) -> "RenderProfile":
        return cls(name="fast_preview", width=540, height=960, fps=15, crf=28, preset="ultrafast")
