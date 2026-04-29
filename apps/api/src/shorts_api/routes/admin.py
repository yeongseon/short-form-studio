from __future__ import annotations

import hmac
import logging
import os
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

admin_service = import_module("creator_service.admin_service").admin_service
logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("admin.audit")


async def require_admin(x_admin_key: str = Header(...)) -> None:
    expected = os.environ.get("ADMIN_API_KEY", "")
    if not expected or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(403, "Admin access denied")


router = APIRouter(
    prefix="",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


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
    active_task_id: str | None = None
    updated_at: Any | None = None


class QueueDepthResponse(BaseModel):
    celery: int
    gpu_queue: int


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
    error: str | None = None


class CacheClearResponse(BaseModel):
    ok: bool
    deleted_keys: int
    key_pattern: str
    dry_run: bool
    matched_keys: list[str] = Field(default_factory=list)
    error: str | None = None


@router.get("/health", response_model=HealthResponse)
async def admin_health() -> dict[str, Any]:
    return await admin_service.get_system_health()


@router.get("/runs/stuck", response_model=list[RunInfo])
async def admin_stuck_runs(
    threshold_minutes: int = Query(default=30, ge=1),
) -> list[dict[str, Any]]:
    return await admin_service.get_stuck_runs(threshold_minutes=threshold_minutes)


@router.get("/tasks/failed", response_model=list[RunInfo])
async def admin_failed_tasks(hours: int = Query(default=24, ge=1)) -> list[dict[str, Any]]:
    return await admin_service.get_failed_tasks(hours=hours)


@router.get("/queue/depth", response_model=QueueDepthResponse)
async def admin_queue_depth() -> dict[str, int]:
    return await admin_service.get_queue_depth()


@router.get("/storage/stats", response_model=StorageStatsResponse)
async def admin_storage_stats() -> dict[str, Any]:
    return await admin_service.get_storage_stats()


@router.post("/runs/{run_id}/unstick", response_model=UnstickRunResponse)
async def admin_unstick_run(run_id: str) -> dict[str, Any]:
    logger.warning("Admin mutation requested: unstick run_id=%s", run_id)
    audit_logger.warning("ADMIN_ACTION: unstick_run | run_id=%s", run_id)
    return await admin_service.unstick_run(run_id)


@router.post("/cache/clear", response_model=CacheClearResponse)
async def admin_clear_cache(
    key_pattern: str | None = Query(default=None),
    dry_run: bool = Query(default=False),
) -> dict[str, Any]:
    logger.warning(
        "Admin mutation requested: clear cache key_pattern=%s dry_run=%s",
        key_pattern,
        dry_run,
    )
    if key_pattern is None:
        audit_logger.warning("ADMIN_ACTION: cache_clear | dry_run=%s", dry_run)
    else:
        audit_logger.warning(
            "ADMIN_ACTION: cache_clear | key_pattern=%s | dry_run=%s",
            key_pattern,
            dry_run,
        )
    return await admin_service.clear_cache(key_pattern=key_pattern, dry_run=dry_run)
