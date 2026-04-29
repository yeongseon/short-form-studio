"""Admin API endpoints service operations for run management and safeguards."""

from __future__ import annotations

import inspect
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, cast

import redis.asyncio as redis
from celery import current_app as celery_app

from creator_service.db import get_pool

_GENERATING_TO_REVIEW_STAGE = {
    "SCRIPT_GENERATING": "SCRIPT_REVIEW",
    "VISUAL_PLAN_GENERATING": "VISUAL_PLAN_REVIEW",
    "VISUAL_ASSET_GENERATING": "VISUAL_ASSET_REVIEW",
    "AUDIO_GENERATING": "SUBTITLE_GENERATING",
    "SUBTITLE_GENERATING": "RENDER_GENERATING",
    "RENDER_GENERATING": "FINAL_REVIEW",
}

_UNSTICK_MIN_AGE_SECONDS = 30 * 60
_STAGE_REQUIRED_ARTIFACTS: dict[str, list[str]] = {
    "SCRIPT_GENERATING": [],
    "SCRIPT_REVIEW": ["script"],
    "VOICE_GENERATING": ["script"],
    "VOICE_REVIEW": ["script", "voice"],
    "VIDEO_GENERATING": ["script", "voice"],
    "VIDEO_REVIEW": ["script", "voice", "video"],
    "COMPLETED": ["script", "voice", "video"],
    "VISUAL_PLAN_REVIEW": ["script"],
    "VISUAL_ASSET_REVIEW": ["script", "visual_plan"],
    "SUBTITLE_GENERATING": ["script", "audio"],
    "RENDER_GENERATING": ["script", "audio", "subtitle"],
    "FINAL_REVIEW": ["script", "audio", "subtitle", "render"],
    "PUBLISHED": ["script", "audio", "subtitle", "render"],
}
logger = logging.getLogger(__name__)


class TaskBroker(Protocol):
    async def revoke_task(self, task_id: str) -> None: ...


class CeleryTaskBroker:
    async def revoke_task(self, task_id: str) -> None:
        cast(Any, celery_app).control.revoke(task_id, terminate=True)


class AdminService:
    def __init__(self, task_broker: TaskBroker | None = None) -> None:
        self._started_at = time.time()
        self._task_broker = task_broker or CeleryTaskBroker()

    def _redis_client(self) -> redis.Redis:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        return redis.from_url(redis_url, decode_responses=True)

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _get_run_artifact_types(self, run_id: int, connection: Any) -> set[str]:
        rows = await connection.fetch(
            "SELECT DISTINCT artifact_type FROM artifacts WHERE run_id = $1",
            run_id,
        )
        return {str(row["artifact_type"]) for row in rows if row.get("artifact_type")}

    def _parse_active_task_ids(self, active_task_id: str | None) -> list[str]:
        if not active_task_id:
            return []
        try:
            parsed = json.loads(active_task_id)
            if isinstance(parsed, str):
                return [parsed] if parsed else []
            if isinstance(parsed, list):
                return [str(task_id) for task_id in parsed if str(task_id)]
        except (ValueError, TypeError):
            pass
        return [active_task_id]

    async def get_system_health(self) -> dict[str, Any]:
        uptime_seconds = int(time.time() - self._started_at)
        health: dict[str, Any] = {
            "status": "ok",
            "db": {"ok": True},
            "redis": {"ok": True},
            "uptime_seconds": uptime_seconds,
        }

        try:
            pool = await get_pool()
            async with pool.acquire() as connection:
                await connection.fetchval("SELECT 1")
        except Exception as exc:
            health["status"] = "degraded"
            health["db"] = {"ok": False, "error": str(exc)}

        client: redis.Redis | None = None
        try:
            client = self._redis_client()
            await self._maybe_await(client.ping())
        except Exception as exc:
            health["status"] = "degraded"
            health["redis"] = {"ok": False, "error": str(exc)}
        finally:
            if client is not None:
                await client.aclose()

        return health

    async def get_stuck_runs(self, threshold_minutes: int = 30) -> list[dict[str, Any]]:
        threshold_minutes = max(1, threshold_minutes)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=threshold_minutes)
        try:
            pool = await get_pool()
            stages = list(_GENERATING_TO_REVIEW_STAGE.keys())
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    """
                    SELECT id, project_id, current_stage, status, active_task_id, updated_at
                    FROM creator_runs
                    WHERE current_stage = ANY($1::text[])
                      AND updated_at < $2
                    ORDER BY updated_at ASC
                    """,
                    stages,
                    cutoff,
                )
            return [dict(row) for row in rows]
        except Exception:
            return []

    async def get_failed_runs(self, hours: int = 24) -> list[dict[str, Any]]:
        hours = max(1, hours)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
        try:
            pool = await get_pool()
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    """
                    SELECT id, project_id, current_stage, status, active_task_id, updated_at
                    FROM creator_runs
                    WHERE status = 'failed'
                      AND updated_at >= $1
                    ORDER BY updated_at DESC
                    """,
                    cutoff,
                )
            return [dict(row) for row in rows]
        except Exception:
            return []

    async def get_queue_depth(self) -> dict[str, int]:
        queue_names = ["creator"]
        result: dict[str, int] = {name: 0 for name in queue_names}
        client: redis.Redis | None = None
        try:
            client = self._redis_client()
            for queue_name in queue_names:
                depth = await self._maybe_await(client.llen(queue_name))
                result[queue_name] = int(depth)
        except Exception:
            return result
        finally:
            if client is not None:
                await client.aclose()
        return result

    async def get_storage_stats(self) -> dict[str, Any]:
        artifact_root = Path(os.getenv("ARTIFACT_ROOT", "./data/artifacts"))
        total_files = 0
        total_size_bytes = 0
        try:
            if artifact_root.exists():
                for file_path in artifact_root.rglob("*"):
                    if file_path.is_file():
                        total_files += 1
                        total_size_bytes += file_path.stat().st_size
            return {
                "artifact_root": str(artifact_root),
                "file_count": total_files,
                "total_size_bytes": total_size_bytes,
            }
        except Exception as exc:
            return {
                "artifact_root": str(artifact_root),
                "file_count": total_files,
                "total_size_bytes": total_size_bytes,
                "error": str(exc),
            }

    async def unstick_run(self, run_id: str) -> dict[str, Any]:
        try:
            run_id_int = int(run_id)
        except ValueError:
            return {"ok": False, "run_id": run_id, "error": "Invalid run_id"}

        try:
            pool = await get_pool()
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    "SELECT id, current_stage, status, active_task_id, updated_at FROM creator_runs WHERE id = $1",
                    run_id_int,
                )
                if row is None:
                    return {"ok": False, "run_id": run_id, "error": "Run not found"}

                current_stage = row["current_stage"]
                target_stage = _GENERATING_TO_REVIEW_STAGE.get(current_stage)
                if target_stage is None:
                    return {
                        "ok": False,
                        "run_id": run_id,
                        "current_stage": current_stage,
                        "error": "Run is not in a generating stage",
                    }

                run_status = row["status"]
                if run_status != "running":
                    return {
                        "ok": False,
                        "run_id": run_id,
                        "current_stage": current_stage,
                        "status": run_status,
                        "error": "Run is not in 'running' status",
                    }

                updated_at = row["updated_at"]
                if not isinstance(updated_at, datetime):
                    return {
                        "ok": False,
                        "run_id": run_id,
                        "current_stage": current_stage,
                        "error": "Run missing stage timestamp",
                    }
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)

                stage_age_seconds = (datetime.now(tz=timezone.utc) - updated_at).total_seconds()
                if stage_age_seconds <= _UNSTICK_MIN_AGE_SECONDS:
                    return {
                        "ok": False,
                        "run_id": run_id,
                        "current_stage": current_stage,
                        "error": "Run has not been stuck long enough",
                    }

                required_artifacts = _STAGE_REQUIRED_ARTIFACTS.get(target_stage, [])
                if required_artifacts:
                    existing_artifacts = await self._get_run_artifact_types(run_id_int, connection)
                    missing_artifacts = [
                        artifact_type
                        for artifact_type in required_artifacts
                        if artifact_type not in existing_artifacts
                    ]
                    if missing_artifacts:
                        return {
                            "ok": False,
                            "run_id": run_id,
                            "current_stage": current_stage,
                            "error": (
                                f"Cannot advance to {target_stage}: missing required artifacts: "
                                f"{missing_artifacts}"
                            ),
                        }

                active_task_id = row["active_task_id"]
                updated = await connection.fetchrow(
                    """
                    UPDATE creator_runs
                    SET current_stage = $2,
                        status = 'pending',
                        active_task_id = NULL
                    WHERE id = $1
                      AND current_stage = $3
                      AND status = $4
                      AND updated_at = $5
                    RETURNING id, current_stage, status, updated_at
                    """,
                    run_id_int,
                    target_stage,
                    current_stage,
                    run_status,
                    row["updated_at"],
                )
                if updated is None:
                    return {
                        "ok": False,
                        "run_id": run_id,
                        "error": "Run changed concurrently; retry unstick",
                    }

                if active_task_id:
                    for task_id in self._parse_active_task_ids(active_task_id):
                        await self._task_broker.revoke_task(task_id)

                logger.warning(
                    "Admin mutation executed: unstick run_id=%s from=%s to=%s age_seconds=%.1f",
                    run_id_int,
                    current_stage,
                    target_stage,
                    stage_age_seconds,
                )

                return {
                    "ok": True,
                    "run_id": str(updated["id"]),
                    "previous_stage": current_stage,
                    "current_stage": updated["current_stage"],
                    "status": updated["status"],
                }
        except Exception as exc:
            return {"ok": False, "run_id": run_id, "error": str(exc)}

    async def clear_cache(
        self, key_pattern: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        protected_keys = {"celery", "gpu_queue"}
        deleted = 0
        resolved_pattern = key_pattern or os.getenv("ADMIN_CACHE_CLEAR_PREFIX", "cache:*")
        # Restrict patterns to cache namespace to prevent accidental data wipe
        if not resolved_pattern.startswith("cache:"):
            return {
                "ok": False,
                "deleted_keys": 0,
                "key_pattern": resolved_pattern,
                "dry_run": dry_run,
                "matched_keys": [],
                "error": "Pattern must start with 'cache:' to prevent accidental data wipe",
            }
        matched_keys: list[str] = []
        client: redis.Redis | None = None
        try:
            client = self._redis_client()
            keys = [key async for key in client.scan_iter(match=resolved_pattern)]
            for key in keys:
                if key in protected_keys:
                    continue
                matched_keys.append(key)
                if dry_run:
                    continue
                deleted_result = client.delete(key)
                if inspect.isawaitable(deleted_result):
                    deleted += int(await deleted_result)
                else:
                    deleted += int(deleted_result)
            logger.warning(
                "Admin mutation executed: clear cache key_pattern=%s dry_run=%s matched=%d deleted=%d",
                resolved_pattern,
                dry_run,
                len(matched_keys),
                deleted,
            )
            return {
                "ok": True,
                "deleted_keys": deleted,
                "key_pattern": resolved_pattern,
                "dry_run": dry_run,
                "matched_keys": matched_keys,
            }
        except Exception as exc:
            return {
                "ok": False,
                "deleted_keys": deleted,
                "key_pattern": resolved_pattern,
                "dry_run": dry_run,
                "matched_keys": matched_keys,
                "error": str(exc),
            }
        finally:
            if client is not None:
                await client.aclose()


admin_service = AdminService()
