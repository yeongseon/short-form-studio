"""SF-48: shared validated EditorCommand boundary — typed command models.

These Pydantic models are the stable contract the editor UI and later AI use to
express Timeline mutations. Each command carries a literal ``type`` so
``EditorCommandModel`` parses the wire payload as a discriminated union to the
right concrete command and rejects unknown types before any application. Shape
validation (bounds, allowlists) lives here; reference/workspace/source-bounds
validation lives in the service-layer applier.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SUPPORTED_TRANSITIONS = Literal["cut", "fade", "ken_burns", "ken_burns_lite"]
_DELETE_POLICY = Literal["gap", "ripple"]
_OUTPUT_PRESET = Literal["short_vertical", "short_square", "short_landscape"]


class TrimSegmentCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["trimSegment"] = "trimSegment"
    segment_id: str = Field(min_length=1, max_length=100)
    trim_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    trim_end_seconds: float = Field(gt=0, allow_inf_nan=False)


class SplitSegmentCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["splitSegment"] = "splitSegment"
    segment_id: str = Field(min_length=1, max_length=100)
    at_seconds: float = Field(ge=0, allow_inf_nan=False)


class DeleteSegmentCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["deleteSegment"] = "deleteSegment"
    segment_id: str = Field(min_length=1, max_length=100)
    policy: _DELETE_POLICY = "ripple"


class ReplaceAssetCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["replaceAsset"] = "replaceAsset"
    segment_id: str = Field(min_length=1, max_length=100)
    asset_id: int = Field(ge=1)


class MoveSegmentCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["moveSegment"] = "moveSegment"
    segment_id: str = Field(min_length=1, max_length=100)
    target_index: int = Field(ge=0)


class ResizeSegmentCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["resizeSegment"] = "resizeSegment"
    segment_id: str = Field(min_length=1, max_length=100)
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)


class SetTransitionCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["setTransition"] = "setTransition"
    segment_id: str = Field(min_length=1, max_length=100)
    transition: _SUPPORTED_TRANSITIONS
    duration_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class SwitchOutputCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["switchOutput"] = "switchOutput"
    preset: _OUTPUT_PRESET


class SetStyleCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["setStyle"] = "setStyle"
    style: str = Field(min_length=1, max_length=100)


class SetAudioCommand(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: Literal["setAudio"] = "setAudio"
    music_volume: float = Field(ge=0, le=1, allow_inf_nan=False)


EditorCommand = Annotated[
    Union[
        TrimSegmentCommand,
        SplitSegmentCommand,
        DeleteSegmentCommand,
        ReplaceAssetCommand,
        MoveSegmentCommand,
        ResizeSegmentCommand,
        SetTransitionCommand,
        SwitchOutputCommand,
        SetStyleCommand,
        SetAudioCommand,
    ],
    Field(discriminator="type"),
]


class EditorCommandModel(BaseModel):
    """Wire wrapper so the discriminated union can be parsed from a raw payload.

    Accepts either ``{"command": {...}}`` or a bare command dict (with a ``type``
    key), so callers can validate a raw command payload directly.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    command: EditorCommand

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_command(cls, data: Any) -> Any:
        if isinstance(data, dict) and "command" not in data and "type" in data:
            return {"command": data}
        return data
