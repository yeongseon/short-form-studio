"""Schemas for visual plan, visual assets, and image generation operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_VALID_SAMPLERS = frozenset(
    {
        "Euler a",
        "Euler",
        "LMS",
        "Heun",
        "DPM2",
        "DPM2 a",
        "DPM++ 2S a",
        "DPM++ 2M",
        "DPM++ SDE",
        "DPM++ 2M Karras",
        "DPM++ SDE Karras",
        "DPM++ 2M SDE Karras",
    }
)


class ImageTuningParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: Annotated[int, Field(ge=10, le=50, description="Denoising steps")] = 25
    cfg_scale: Annotated[int | float, Field(ge=1, le=20, description="CFG scale")] = 7
    sampler_name: Annotated[
        str,
        Field(max_length=40, description="Sampler algorithm"),
    ] = "DPM++ 2M Karras"
    negative_prompt: Annotated[
        str,
        Field(max_length=1000, description="Negative prompt"),
    ] = ""

    @field_validator("sampler_name")
    @classmethod
    def validate_sampler(cls, v: str) -> str:
        if v not in _VALID_SAMPLERS:
            raise ValueError(f"Invalid sampler '{v}'. Must be one of: {sorted(_VALID_SAMPLERS)}")
        return v


class GenerateVisualAssetsRequest(BaseModel):
    model_key: str = "sd15"
    image_params: ImageTuningParams | None = None


class ReplaceVisualPlanRequest(BaseModel):
    scenes: list[dict[str, object]] = Field(min_length=1, max_length=200)


class PatchSceneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, max_length=2000)
    prompt_edited: bool | None = None
    prompt_source: Literal["auto_generated", "user_edited", "model_suggested"] | None = None
    style_tags: list[Annotated[str, Field(max_length=256)]] | None = Field(
        default=None, max_length=32
    )
    mood: str | None = Field(default=None, max_length=256)
    composition: str | None = Field(default=None, max_length=256)
    expected_version: int | None = None


class RegenerateSceneImageRequest(BaseModel):
    model_key: str = "sd15"
    prompt_override: str | None = Field(default=None, max_length=2000)
    image_params: ImageTuningParams | None = None


class GenerateSceneImageRequest(BaseModel):
    model_key: str = "sd15"
    image_params: ImageTuningParams | None = None
