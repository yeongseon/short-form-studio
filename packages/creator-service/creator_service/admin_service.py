from __future__ import annotations

import inspect
import logging
import os
import time
from importlib import import_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import redis.asyncio as redis

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
logger = logging.getLogger(__name__)


class AdminService:
    def __init__(self) -> None:
        self._started_at = time.time()

    def _redis_client(self) -> redis.Redis:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        return redis.from_url(redis_url, decode_responses=True)

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

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

    async def get_failed_tasks(self, hours: int = 24) -> list[dict[str, Any]]:
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
        queue_names = ["celery", "gpu_queue"]
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

                active_task_id = row["active_task_id"]
                if active_task_id:
                    creator_runs_utils = import_module("shorts_api.routes.creator_runs_utils")
                    creator_runs_utils._revoke_active_tasks(active_task_id)

                updated = await connection.fetchrow(
                    """
                    UPDATE creator_runs
                    SET current_stage = $2,
                        active_task_id = NULL
                    WHERE id = $1
                    RETURNING id, current_stage, updated_at
                    """,
                    run_id_int,
                    target_stage,
                )
                if updated is None:
                    return {"ok": False, "run_id": run_id, "error": "Failed to update run"}

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
