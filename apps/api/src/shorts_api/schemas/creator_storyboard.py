"""Schemas for storyboard paragraph-level operations (TTS, subtitles)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParagraphAudioRequest(BaseModel):
    tts_model: str = Field(default="qwen3-tts", max_length=256)
    voice: str = Field(default="default", max_length=256)


class ParagraphSubtitlesRequest(BaseModel):
    subtitle_model: str = Field(default="whisper-small", max_length=256)
    subtitle_format: Literal["srt", "vtt"] = "srt"


class BulkParagraphAudioRequest(BaseModel):
    tts_model: str = Field(default="qwen3-tts", max_length=256)
    voice: str = Field(default="default", max_length=256)


class BulkParagraphSubtitlesRequest(BaseModel):
    subtitle_model: str = Field(default="whisper-small", max_length=256)
    subtitle_format: Literal["srt", "vtt"] = "srt"
