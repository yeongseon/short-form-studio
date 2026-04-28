from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UsageEvent(BaseModel):
    id: int
    workspace_id: int | None = None
    project_id: int | None = None
    run_id: int | None = None
    provider: str
    model_key: str
    operation_type: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    image_count: int | None = None
    audio_seconds: float | None = None
    estimated_cost_usd: float | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, object]) -> UsageEvent:
        return cls.model_validate(row)


class WorkspaceQuota(BaseModel):
    id: int
    workspace_id: int
    monthly_llm_calls: int = 1000
    monthly_image_generations: int = 200
    monthly_tts_seconds: int = 3600
    monthly_cost_usd: float = 50.0
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, object]) -> WorkspaceQuota:
        return cls.model_validate(row)


class UsageSummary(BaseModel):
    total_llm_calls: int
    total_image_generations: int
    total_tts_seconds: float
    total_estimated_cost_usd: float
    by_provider: dict[str, float]
    by_operation: dict[str, int]
    period_start: datetime
    period_end: datetime
