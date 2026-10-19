from __future__ import annotations

from datetime import datetime, timezone

from celery_app import celery_app
from creator_service.media_retention import MediaRetentionPolicy, MediaRetentionService
from creator_service.object_storage import get_storage_backend
from creator_service.postgres_media_asset_storage import PostgresMediaAssetStorage
from worker_loop import run_in_worker_loop


async def _sweep_once() -> dict[str, int | bool]:
    storage = PostgresMediaAssetStorage()
    policy = MediaRetentionPolicy.from_env()
    totals = {"candidates": 0, "deleted": 0}
    if policy.enabled:
        service = MediaRetentionService(storage, get_storage_backend(), policy)
        after_workspace_id: int | None = None
        while workspace_ids := await storage.list_retention_workspaces(
            1000, after_workspace_id=after_workspace_id,
        ):
            for workspace_id in workspace_ids:
                result = await service.sweep_workspace(
                    workspace_id, now=datetime.now(timezone.utc),
                )
                totals["candidates"] += result.candidates
                totals["deleted"] += result.deleted
            after_workspace_id = workspace_ids[-1]
    return {**totals, "dry_run": policy.dry_run, "enabled": policy.enabled}


@celery_app.task(name="sweep_media_retention", ignore_result=True)
def sweep_media_retention() -> dict[str, int | bool]:
    return run_in_worker_loop(_sweep_once())
