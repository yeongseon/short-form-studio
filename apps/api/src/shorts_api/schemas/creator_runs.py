"""Schemas for pipeline run operations — create, approve, generate, restart."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

# --- Env-configurable model defaults ---
_SCRIPT_DEFAULT_MODEL = os.getenv("SCRIPT_DEFAULT_MODEL", "qwen3-4b")
_TTS_DEFAULT_MODEL = os.getenv("TTS_DEFAULT_MODEL", "edge-tts")
_SUBTITLE_DEFAULT_MODEL = os.getenv("SUBTITLE_DEFAULT_MODEL", "whisper-small")
_RENDER_DEFAULT_PROFILE = os.getenv("RENDER_DEFAULT_PROFILE", "shorts_default")


class CreateRunRequest(BaseModel):
    model_defaults: dict[str, str] | None = None
    style_preset: str = Field(default="default", max_length=256)
    metadata: dict[str, object] | None = None


class RestartRunRequest(BaseModel):
    stage: Literal[
        "IDEA_READY",
        "SCRIPT_GENERATING",
        "SCRIPT_REVIEW",
        "VISUAL_PLAN_SETUP",
        "VISUAL_PLAN_GENERATING",
        "VISUAL_PLAN_REVIEW",
        "VISUAL_ASSET_GENERATING",
        "VISUAL_ASSET_REVIEW",
        "AUDIO_GENERATING",
        "SUBTITLE_GENERATING",
        "RENDER_GENERATING",
        "FINAL_REVIEW",
        "PUBLISHED",
        "FAILED",
    ]


class ApproveScriptRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


class ApproveVisualPlanRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


class ApproveVisualAssetsRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


class ApproveFinalRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


class GenerateScriptRequest(BaseModel):
    model_key: str = Field(default=_SCRIPT_DEFAULT_MODEL, max_length=256)
    instructions: str | None = Field(default=None, max_length=32_000)
    niche: (
        Literal[
            "facts",
            "horror",
            "motivation",
            "psychology",
            "science",
            "food",
            "tech",
            "family_story",
            "ssul_dc",
        ]
        | None
    ) = None
    language: Literal["ko", "en", "ja", "zh", "es", "pt", "fr", "de"] = "ko"


class GenerateVisualPlanRequest(BaseModel):
    model_key: str = Field(default=_SCRIPT_DEFAULT_MODEL, max_length=256)
    style_preset: str | None = Field(default=None, max_length=200)
    niche: (
        Literal[
            "facts",
            "horror",
            "motivation",
            "psychology",
            "science",
            "food",
            "tech",
            "family_story",
            "ssul_dc",
        ]
        | None
    ) = None


class GenerateAudioRequest(BaseModel):
    tts_model: str = Field(default=_TTS_DEFAULT_MODEL, max_length=256)
    voice: str = Field(default="default", max_length=256)


class GenerateSubtitlesRequest(BaseModel):
    subtitle_model: str = Field(default=_SUBTITLE_DEFAULT_MODEL, max_length=256)
    subtitle_format: Literal["srt", "vtt"] = "srt"


class RenderRequest(BaseModel):
    render_profile: str = Field(default=_RENDER_DEFAULT_PROFILE, max_length=256)


class UpdateModelDefaultsRequest(BaseModel):
    script_model: str | None = Field(default=None, max_length=256)
    image_model: str | None = Field(default=None, max_length=256)
    tts_model: str | None = Field(default=None, max_length=256)
    subtitle_model: str | None = Field(default=None, max_length=256)
    render_profile: str | None = Field(default=None, max_length=256)
