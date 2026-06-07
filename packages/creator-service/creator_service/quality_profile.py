"""Quality profiles that thread beat metadata from script → render.

A quality profile defines the full pipeline configuration for a content type.
ssul_v2 is optimized for Korean 썰쇼츠 (story-time shorts).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BeatMetadata:
    """Per-scene beat info threaded through the pipeline."""

    beat_type: str  # "hook", "tension", "climax", "resolution", "cta"
    emotion: str  # "surprise", "fear", "empathy", "relief", "curiosity"
    pacing: str  # "fast", "normal", "slow", "pause"
    emphasis_words: list[str] = field(default_factory=list)
    sfx_hint: str | None = None  # e.g. "whoosh", "heartbeat", "silence"


@dataclass
class QualityProfile:
    """Full pipeline configuration for a content type."""

    name: str
    # Script
    min_scenes: int = 5
    max_scenes: int = 8
    target_duration_seconds: tuple[int, int] = (45, 70)
    banned_patterns: list[str] = field(default_factory=list)
    required_structure: list[str] = field(default_factory=list)
    # Image
    image_provider: str = "pollinations"
    image_style_prefix: str = ""
    image_negative_prompt: str = ""
    # Render
    transition: str = "ken_burns"  # ken_burns, fade, cut
    ken_burns_zoom: tuple[float, float] = (1.0, 1.15)
    crossfade_ms: int = 300
    # Subtitles
    subtitle_emphasis: bool = True
    emphasis_color: str = "&H0000FFFF"  # yellow in ASS BGR
    emphasis_scale: float = 1.3
    # Audio
    tts_rate: str = "+10%"
    bgm_volume: float = 0.25
    bgm_mood: str = "emotional"
    # Pacing
    min_scene_duration: float = 4.0
    max_scene_duration: float = 12.0

    def to_render_kwargs(self) -> dict[str, Any]:
        """Convert to kwargs for RenderProfile/FFmpegService."""
        return {
            "transition": self.transition,
            "ken_burns_zoom": self.ken_burns_zoom,
            "crossfade_ms": self.crossfade_ms,
        }

    def to_tts_params(self) -> dict[str, str]:
        """Convert to params for EdgeTTS provider."""
        return {"rate": self.tts_rate}

    def to_bgm_kwargs(self) -> dict[str, Any]:
        """Convert to kwargs for BgmService."""
        return {
            "bgm_volume": self.bgm_volume,
            "mood": self.bgm_mood,
        }


# --- Registry ---
QUALITY_PROFILES: dict[str, QualityProfile] = {
    "ssul_v2": QualityProfile(
        name="ssul_v2",
        min_scenes=3,
        max_scenes=6,
        target_duration_seconds=(30, 50),
        banned_patterns=[
            "구독",
            "좋아요",
            "알림",
            "subscribe",
            "like",
            "이 영상에서는",
            "오늘은",
            "안녕하세요",
        ],
        required_structure=["hook", "body", "conclusion"],
        image_provider="pollinations",
        image_style_prefix=(
            "cinematic Korean drama style, moody lighting, shallow depth of field, film grain, "
        ),
        image_negative_prompt="text, watermark, logo, cartoon, anime, low quality, blurry",
        transition="fade",
        ken_burns_zoom=(1.0, 1.15),
        crossfade_ms=200,
        subtitle_emphasis=True,
        emphasis_color="&H0000FFFF",  # yellow
        emphasis_scale=1.3,
        tts_rate="+15%",  # slightly faster for urgency
        bgm_volume=0.20,
        bgm_mood="suspense",
        min_scene_duration=3.0,
        max_scene_duration=10.0,
    ),
    "default": QualityProfile(
        name="default",
        image_provider="groq-svg",
        transition="cut",
        subtitle_emphasis=False,
        tts_rate="+0%",
        bgm_volume=0.35,
        bgm_mood="emotional",
    ),
}


def get_quality_profile(name: str = "ssul_v2") -> QualityProfile:
    """Get a quality profile by name, defaulting to ssul_v2."""
    return QUALITY_PROFILES.get(name, QUALITY_PROFILES["ssul_v2"])
