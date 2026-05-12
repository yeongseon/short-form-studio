"""Admin API endpoints for operational control and observability.

Auth boundary:
- ``/api/admin/*`` routes authenticate with ``X-Admin-Key``.
- ``/api/creator/*`` routes authenticate with ``X-API-Key`` or ``Authorization: Bearer``.
- These are separate auth domains and credentials are not interchangeable.

This module exposes backend-only admin endpoints under ``/api/admin``.
It does not implement any admin dashboard UI; frontend dashboard work is
handled separately from this API surface.
"""

from __future__ import annotations

import hmac
import hashlib
import logging
import os
import sys
import time
from collections import defaultdict
from importlib import import_module
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError

try:
    admin_service = import_module("creator_service.admin_service").admin_service
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[5]
    creator_service_pkg = repo_root / "packages" / "creator-service"
    if str(creator_service_pkg) not in sys.path:
        sys.path.append(str(creator_service_pkg))
    admin_service = import_module("creator_service.admin_service").admin_service
logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("admin.audit")


class DestructiveOpRateLimiter:
    """In-memory rate limiter for destructive admin operations."""

    def __init__(self, max_ops_per_minute: int = 10):
        self.max_ops_per_minute = max_ops_per_minute
        # Track operations per admin key: key -> list of timestamps
        self.operations: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, endpoint_or_admin_key: str, admin_key: str | None = None) -> bool:
        """Check if operation is allowed for the given admin key."""
        key = admin_key if admin_key is not None else endpoint_or_admin_key
        now = time.time()
        one_minute_ago = now - 60

        # Clean up old operations
        if key in self.operations:
            self.operations[key] = [ts for ts in self.operations[key] if ts > one_minute_ago]

        # Check if we're under the limit
        if len(self.operations[key]) < self.max_ops_per_minute:
            self.operations[key].append(now)
            return True
        return False

    def get_remaining_ops(self, admin_key: str) -> int:
        """Get remaining operations for this minute."""
        now = time.time()
        one_minute_ago = now - 60

        if admin_key in self.operations:
            recent = [ts for ts in self.operations[admin_key] if ts > one_minute_ago]
            return max(0, self.max_ops_per_minute - len(recent))
        return self.max_ops_per_minute


class RedisRateLimiter:
    # Redis-based rate limiting ensures consistency across multiple API replicas
    def __init__(
        self,
        max_ops: int = 10,
        window_seconds: int = 60,
        redis_url: str | None = None,
    ):
        self.max_ops = max_ops
        self.window_seconds = window_seconds
        self._fallback = DestructiveOpRateLimiter(max_ops_per_minute=max_ops)
        self._redis: Redis | None = None
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self._redis_retry_after: float = 0.0

    @staticmethod
    def _key_hash(admin_key: str) -> str:
        return hashlib.sha256(admin_key.encode("utf-8")).hexdigest()

    def _redis_key(self, endpoint: str, admin_key: str) -> str:
        endpoint_key = endpoint.strip("/").replace("/", ":") or "root"
        return f"ratelimit:{endpoint_key}:{self._key_hash(admin_key)}"

    def is_allowed(self, endpoint: str, admin_key: str) -> bool:
        if self._redis is None and time.time() >= self._redis_retry_after:
            try:
                client = Redis.from_url(self._redis_url, decode_responses=True)
                client.ping()
                self._redis = client
                logger.info("Redis rate limiter reconnected successfully")
            except Exception:
                self._redis_retry_after = time.time() + 60

        if self._redis is None:
            return self._fallback.is_allowed(admin_key)

        try:
            key = self._redis_key(endpoint, admin_key)
            with self._redis.pipeline() as pipe:
                pipe.incr(key)
                pipe.expire(key, self.window_seconds)
                count, _ = pipe.execute()
            return int(count) <= self.max_ops
        except RedisError as exc:
            logger.warning(
                "Redis rate limit operation failed; falling back to in-memory limiter (will retry in 60s): %s",
                exc,
            )
            self._redis = None
            self._redis_retry_after = time.time() + 60
            return self._fallback.is_allowed(admin_key)


# Global rate limiter instance
_rate_limiter = RedisRateLimiter(max_ops=10, window_seconds=60)


async def require_admin(x_admin_key: str | None = Header(default=None)) -> str:
    if not x_admin_key:
        raise HTTPException(status_code=401, detail="Admin access denied")

    expected = os.environ.get("ADMIN_API_KEY", "")
    if not expected or len(expected) < 16:
        logger.error("ADMIN_API_KEY is not set or too short (min 16 chars)")
        raise HTTPException(status_code=503, detail="Admin API not configured")
    if not expected or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=403, detail="Admin access denied")
    return x_admin_key


async def require_confirmation_and_rate_limit(
    x_confirm_action: str = Header(None), x_admin_key: str = Depends(require_admin)
) -> None:
    """Middleware to ensure destructive operations have confirmation header and respect rate limits."""
    # Check confirmation header
    if not x_confirm_action or x_confirm_action.lower() != "yes":
        raise HTTPException(
            status_code=400,
            detail="Destructive operation requires X-Confirm-Action: yes header",
        )

    # Check rate limit
    if not _rate_limiter.is_allowed("admin:destructive", x_admin_key):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: maximum 10 destructive operations per minute",
        )


router = APIRouter(
    prefix="",
    tags=["admin-api"],
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


@router.get("/runs/failed", response_model=list[RunInfo])
async def admin_failed_runs(hours: int = Query(default=24, ge=1)) -> list[dict[str, Any]]:
    return await admin_service.get_failed_runs(hours=hours)


@router.get("/queue/depth", response_model=QueueDepthResponse)
async def admin_queue_depth() -> dict[str, int]:
    return await admin_service.get_queue_depth()


@router.get("/storage/stats", response_model=StorageStatsResponse)
async def admin_storage_stats() -> dict[str, Any]:
    return await admin_service.get_storage_stats()


@router.post("/runs/{run_id}/unstick", response_model=UnstickRunResponse)
async def admin_unstick_run(
    run_id: str,
    admin_key: str = Depends(require_admin),
    _: None = Depends(require_confirmation_and_rate_limit),
) -> dict[str, Any]:
    key_fingerprint = hashlib.sha256(admin_key.encode()).hexdigest()[:8]
    logger.warning("Admin mutation requested: unstick run_id=%s", run_id)
    audit_logger.warning("ADMIN_ACTION: unstick_run | run_id=%s | key=%s", run_id, key_fingerprint)
    return await admin_service.unstick_run(run_id)


@router.post("/cache/clear", response_model=CacheClearResponse)
async def admin_clear_cache(
    key_pattern: str | None = Query(default=None),
    dry_run: bool = Query(default=False),
    admin_key: str = Depends(require_admin),
    _: None = Depends(require_confirmation_and_rate_limit),
) -> dict[str, Any]:
    key_fingerprint = hashlib.sha256(admin_key.encode()).hexdigest()[:8]
    logger.warning(
        "Admin mutation requested: clear cache key_pattern=%s dry_run=%s",
        key_pattern,
        dry_run,
    )
    if key_pattern is None:
        audit_logger.warning(
            "ADMIN_ACTION: cache_clear | dry_run=%s | key=%s", dry_run, key_fingerprint
        )
    else:
        audit_logger.warning(
            "ADMIN_ACTION: cache_clear | key_pattern=%s | dry_run=%s | key=%s",
            key_pattern,
            dry_run,
            key_fingerprint,
        )
    return await admin_service.clear_cache(key_pattern=key_pattern, dry_run=dry_run)
