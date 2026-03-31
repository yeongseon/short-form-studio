"""Storyboard domain models for unified paragraph-based pipeline.

Each storyboard paragraph represents one section of the script, with its
associated image, audio, and subtitles.  The StoryboardResponse aggregates
all paragraphs for a run into a single view.

Key invariant: 1 paragraph = 1 image = 1 audio = N subtitles.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


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
    """Tracks which downstream artifacts are stale after an upstream edit."""

    prompt_stale: bool = False
    image_stale: bool = False
    audio_stale: bool = False
    subtitles_stale: bool = False


class StoryboardParagraph(BaseModel):
    """One paragraph in the unified storyboard view."""

    section_id: str
    order: int
    text: str
    display_text: str | None = None
    image_prompt: str | None = None
    image_url: str | None = None
    audio_url: str | None = None
    audio_duration: float | None = None
    subtitles_url: str | None = None
    subtitle_entries: list[dict[str, object]] | None = None
    status: ParagraphStatus = ParagraphStatus.IDLE
    stale_flags: StaleFlags | None = None

    # Scene/asset metadata for cross-reference
    scene_id: str | None = None
    image_asset_id: int | None = None
    audio_artifact_id: int | None = None
    subtitle_artifact_id: int | None = None


class StoryboardResponse(BaseModel):
    """Full storyboard data for a run."""

    run_id: int
    paragraphs: list[StoryboardParagraph]
    render_ready: bool = False
    total_paragraphs: int = 0
    ready_paragraphs: int = 0
