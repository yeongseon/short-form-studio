from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class UsageEvent(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", protected_namespaces=())

    id: int = Field(ge=1)
    workspace_id: int | None = Field(default=None, ge=1)
    project_id: int | None = Field(default=None, ge=1)
    run_id: int | None = Field(default=None, ge=1)
    provider: str = Field(max_length=50)
    model_key: str = Field(max_length=100)
    operation_type: Literal["llm", "image_gen", "tts", "stt", "render"]
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    image_count: int | None = Field(default=None, ge=0)
    audio_seconds: float | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, object]) -> UsageEvent:
        mapped = dict(row)
        _ = mapped.pop("cost_config_version", None)
        known = set(cls.model_fields)
        filtered = {key: value for key, value in mapped.items() if key in known}
        return cls.model_validate(filtered)


class WorkspaceQuota(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    workspace_id: int = Field(ge=1)
    monthly_llm_calls: int = Field(ge=0, default=1000)
    monthly_image_generations: int = Field(ge=0, default=200)
    monthly_tts_requests: int = Field(ge=0, default=3600)
    monthly_cost_usd: float = Field(ge=0, default=50.0)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, object]) -> WorkspaceQuota:
        known = set(cls.model_fields)
        mapped = {key: value for key, value in row.items() if key in known}
        return cls.model_validate(mapped)


class UsageSummary(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    total_llm_calls: int = Field(ge=0)
    total_image_generations: int = Field(ge=0)
    total_tts_seconds: float = Field(ge=0)
    total_estimated_cost_usd: float = Field(ge=0)
    by_provider: dict[str, float]
    by_operation: dict[str, int]
    period_start: datetime
    period_end: datetime
