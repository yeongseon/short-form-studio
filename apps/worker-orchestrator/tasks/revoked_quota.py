from __future__ import annotations

import logging
from typing import Any

from celery.signals import task_revoked


@task_revoked.connect
def release_revoked_task_quota(request: Any = None, **_: Any) -> None:
    task_id = getattr(request, "id", None)
    if not isinstance(task_id, str):
        return
    from creator_service.usage_service import usage_service
    from worker_loop import run_in_worker_loop

    try:
        run_in_worker_loop(usage_service.finalize_revoked_owned(task_id))
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to release revoked task quota",
            extra={"task_id": task_id},
            exc_info=True,
        )
