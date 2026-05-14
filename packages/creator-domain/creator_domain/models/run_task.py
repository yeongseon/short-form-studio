from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunTask(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    task_type: str = Field(max_length=64)
    celery_task_id: str = Field(max_length=256)
    status: Literal["queued", "pending", "running", "success", "failed", "revoked", "rejected"] = (
        "queued"
    )
    attempt: int = Field(ge=1, default=1)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, object]) -> RunTask:
        return cls.model_validate(row)
