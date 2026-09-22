import concurrent.futures
import logging
import os
from importlib import import_module
from inspect import ismethod
from types import SimpleNamespace
from typing import Protocol
from uuid import uuid4

import anyio
from celery import Task
from creator_domain.task_dispatch import SynchronousTaskExecutionError, TaskSubmission
from creator_service.task_dispatch_service import task_dispatch_service
from pydantic import JsonValue

logger = logging.getLogger(__name__)


class TaskResult(Protocol):
    @property
    def id(self) -> str: ...


class WorkerTask(Protocol):
    def apply_async(
        self, *, args: list[JsonValue], kwargs: dict[str, JsonValue],
        headers: dict[str, str], task_id: str | None = None,
    ) -> TaskResult: ...

    def run(self, context: SimpleNamespace, *args: JsonValue, **kwargs: JsonValue) -> JsonValue: ...


class ApplicationTaskDispatcher:
    def uses_queue(self) -> bool:
        return bool(os.environ.get("REDIS_URL"))

    def _get_trace_headers(self) -> dict[str, str]:
        from creator_service.telemetry import get_trace_headers

        return get_trace_headers()

    def _load_task(self, submission: TaskSubmission) -> WorkerTask:
        module = import_module(f"tasks.{submission.task_name}")
        return getattr(module, submission.task_name)

    def cancel(self, task_id: str) -> None:
        from celery_app import celery_app

        celery_app.control.revoke(task_id, terminate=True)

    def _mark_run_failed(self, run_id: int) -> None:
        async def update_failed() -> None:
            from creator_service.run_service import run_service

            try:
                await run_service.storage.update_run(run_id, {"current_stage": "FAILED", "status": "failed"})
            except Exception:
                logger.warning("Failed to mark run FAILED", extra={"run_id": run_id}, exc_info=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(anyio.run, update_failed).result()

    def dispatch(self, submission: TaskSubmission) -> str:
        task = self._load_task(submission)
        args, kwargs = list(submission.args), dict(submission.kwargs)
        if self.uses_queue() or not hasattr(task, "run"):
            headers = self._get_trace_headers()
            if submission.task_id is None:
                result = task.apply_async(args=args, kwargs=kwargs, headers=headers)
            else:
                result = task.apply_async(args=args, kwargs=kwargs, headers=headers, task_id=submission.task_id)
            return str(result.id)

        task_id = submission.task_id or f"sync-{submission.task_name}-{submission.run_id}-{uuid4().hex[:12]}"
        context = SimpleNamespace(request=SimpleNamespace(id=task_id, retries=0), max_retries=0)
        runner = task.run
        if isinstance(task, Task):
            runner = getattr(task, "_orig_run", task.run)
            if ismethod(runner):
                runner = runner.__func__
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(runner, context, *args, **kwargs).result()
        except Exception as exc:
            logger.exception("Synchronous task dispatch failed", extra={"task": submission.task_name, "run_id": submission.run_id})
            self._mark_run_failed(submission.run_id)
            raise SynchronousTaskExecutionError(f"Synchronous task execution failed for {submission.task_name}") from exc
        return task_id


def initialize_task_dispatch() -> None:
    task_dispatch_service.configure(ApplicationTaskDispatcher())
