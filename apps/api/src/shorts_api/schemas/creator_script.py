"""Schemas for script import and update operations."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ImportMarkdownRequest(BaseModel):
    markdown: str = Field(..., max_length=500_000)
    model_defaults: dict[str, str] | None = None
    style_preset: str = Field(default="default", max_length=200)


class ImportJsonRequest(BaseModel):
    json_script: str = Field(..., max_length=500_000)
    model_defaults: dict[str, str] | None = None
    style_preset: str = Field(default="default", max_length=200)


class UpdateMarkdownRequest(BaseModel):
    markdown: str = Field(..., max_length=500_000)


class UpdateStructuredRequest(BaseModel):
    sections: list[dict[str, object]] = Field(..., max_length=200)


class UpdateJsonScriptRequest(BaseModel):
    json_script: str = Field(..., max_length=500_000)
