from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RunTask(BaseModel):
    id: int
    run_id: int
    task_type: str
    celery_task_id: str
    status: Literal["queued", "pending", "running", "success", "failed", "revoked", "rejected"] = (
        "queued"
    )
    attempt: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, object]) -> RunTask:
        return cls.model_validate(row)
