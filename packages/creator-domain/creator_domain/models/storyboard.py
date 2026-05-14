"""Storyboard domain models for unified paragraph-based pipeline.

Each storyboard paragraph represents one section of the script, with its
associated image, audio, and subtitles.  The StoryboardResponse aggregates
all paragraphs for a run into a single view.

Key invariant: 1 paragraph = 1 image = 1 audio = N subtitles.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ParagraphStatus(str, Enum):
    """Per-paragraph generation status."""

    IDLE = "idle"
    GENERATING_IMAGE = "generating_image"
    GENERATING_AUDIO = "generating_audio"
    GENERATING_SUBTITLES = "generating_subtitles"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


class StaleFlags(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    """Tracks which downstream artifacts are stale after an upstream edit."""

    prompt_stale: bool = False
    image_stale: bool = False
    audio_stale: bool = False
    subtitles_stale: bool = False


class StoryboardParagraph(BaseModel):
    """One paragraph in the unified storyboard view."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    section_id: str = Field(max_length=128)
    order: int = Field(ge=0)
    text: str
    display_text: str | None = None
    image_prompt: str | None = None
    image_url: str | None = None
    audio_url: str | None = None
    audio_duration: float | None = Field(default=None, ge=0)
    subtitles_url: str | None = None
    subtitle_entries: list[dict[str, object]] | None = None
    status: ParagraphStatus = ParagraphStatus.IDLE
    stale_flags: StaleFlags | None = None

    # Scene/asset metadata for cross-reference
    scene_id: str | None = Field(default=None, max_length=128)
    image_asset_id: int | None = Field(default=None, ge=1)
    audio_artifact_id: int | None = Field(default=None, ge=1)
    subtitle_artifact_id: int | None = Field(default=None, ge=1)


class StoryboardResponse(BaseModel):
    """Full storyboard data for a run."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    run_id: int = Field(ge=1)
    paragraphs: list[StoryboardParagraph]
    render_ready: bool = False
    total_paragraphs: int = Field(ge=0, default=0)
    ready_paragraphs: int = Field(ge=0, default=0)
