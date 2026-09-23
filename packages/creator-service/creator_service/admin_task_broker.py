from functools import partial
from typing import Protocol

from celery import current_app

from creator_service.blocking_io import run_control


class TaskBroker(Protocol):
    async def revoke_task(self, task_id: str) -> None: ...


class CeleryTaskBroker:
    async def revoke_task(self, task_id: str) -> None:
        await run_control(partial(current_app.control.revoke, task_id, terminate=True))
