from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RunTask(BaseModel):
    id: int
    run_id: int
    task_type: str
    celery_task_id: str
    status: Literal["pending", "running", "success", "failed", "revoked"] = "pending"
    attempt: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> RunTask:
        return cls.model_validate(row)
