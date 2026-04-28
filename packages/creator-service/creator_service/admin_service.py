from __future__ import annotations

import inspect
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import redis.asyncio as redis

from creator_service.db import get_pool

_GENERATING_TO_REVIEW_STAGE = {
    "SCRIPT_GENERATING": "SCRIPT_REVIEW",
    "VISUAL_PLAN_GENERATING": "VISUAL_PLAN_REVIEW",
    "VISUAL_ASSET_GENERATING": "VISUAL_ASSET_REVIEW",
    "AUDIO_GENERATING": "AUDIO_REVIEW",
    "SUBTITLE_GENERATING": "SUBTITLE_REVIEW",
    "RENDER_GENERATING": "FINAL_REVIEW",
}


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
                    "SELECT id, current_stage FROM creator_runs WHERE id = $1",
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

                updated = await connection.fetchrow(
                    """
                    UPDATE creator_runs
                    SET current_stage = $2
                    WHERE id = $1
                    RETURNING id, current_stage, updated_at
                    """,
                    run_id_int,
                    target_stage,
                )
                if updated is None:
                    return {"ok": False, "run_id": run_id, "error": "Failed to update run"}

                return {
                    "ok": True,
                    "run_id": str(updated["id"]),
                    "previous_stage": current_stage,
                    "current_stage": updated["current_stage"],
                }
        except Exception as exc:
            return {"ok": False, "run_id": run_id, "error": str(exc)}

    async def clear_cache(self) -> dict[str, Any]:
        protected_keys = {"celery", "gpu_queue"}
        deleted = 0
        client: redis.Redis | None = None
        try:
            client = self._redis_client()
            keys = [key async for key in client.scan_iter(match="*")]
            for key in keys:
                if key in protected_keys:
                    continue
                deleted_result = client.delete(key)
                if inspect.isawaitable(deleted_result):
                    deleted += int(await deleted_result)
                else:
                    deleted += int(deleted_result)
            return {"ok": True, "deleted_keys": deleted}
        except Exception as exc:
            return {"ok": False, "deleted_keys": deleted, "error": str(exc)}
        finally:
            if client is not None:
                await client.aclose()


admin_service = AdminService()
