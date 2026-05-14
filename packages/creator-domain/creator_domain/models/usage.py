from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class UsageEvent(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    workspace_id: int | None = None
    project_id: int | None = None
    run_id: int | None = None
    provider: str
    model_key: str
    operation_type: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    image_count: int | None = None
    audio_seconds: float | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, object]) -> UsageEvent:
        mapped = dict(row)
        _ = mapped.pop("cost_config_version", None)
        return cls.model_validate(mapped)


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
        return cls.model_validate(row)


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
