"""Admin API request/response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    db: dict[str, Any]
    redis: dict[str, Any]
    uptime_seconds: int


class RunInfo(BaseModel):
    id: int
    project_id: int
    current_stage: str | None = None
    status: str | None = None
    updated_at: Any | None = None


class QueueDepthResponse(BaseModel):
    creator: int


class StorageStatsResponse(BaseModel):
    artifact_root: str
    file_count: int
    total_size_bytes: int
    error: str | None = None


class UnstickRunResponse(BaseModel):
    ok: bool
    run_id: str
    previous_stage: str | None = None
    current_stage: str | None = None
    status: str | None = None
    audit_id: str | None = None
    error: str | None = None


class CacheClearResponse(BaseModel):
    ok: bool
    deleted_keys: int
    key_pattern: str
    dry_run: bool
    matched_keys: list[str] = Field(default_factory=list)
    audit_id: str | None = None
    error: str | None = None
