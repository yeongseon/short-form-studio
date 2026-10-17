from __future__ import annotations

from dataclasses import asdict

from celery_app import celery_app
from worker_loop import run_in_worker_loop


async def _reconcile_once() -> dict[str, int]:
    from creator_service.media_upload_reconciliation import MediaUploadReconciler
    from creator_service.object_storage import get_storage_backend
    from creator_service.postgres_media_asset_storage import PostgresMediaAssetStorage

    result = await MediaUploadReconciler(
        get_storage_backend(), PostgresMediaAssetStorage(),
    ).sweep()
    return asdict(result)


@celery_app.task(name="reconcile_media_uploads", ignore_result=True)
def reconcile_media_uploads() -> dict[str, int]:
    return run_in_worker_loop(_reconcile_once())
