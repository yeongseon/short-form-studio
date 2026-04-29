from __future__ import annotations

import logging
import sys
import threading
from concurrent.futures import Future
from importlib import import_module
from pathlib import Path
from types import ModuleType
from uuid import uuid4

logger = logging.getLogger(__name__)


class _NoOpCeleryApp:
    def task(self, *args: object, **kwargs: object):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def _decorator(func: object) -> object:
            return func

        return _decorator


class _FakeRequest:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeTaskSelf:
    def __init__(self, task_id: str) -> None:
        self.request = _FakeRequest(task_id)


def _ensure_worker_import_context() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    worker_root = repo_root / "apps" / "worker-orchestrator"

    worker_root_str = str(worker_root)
    if worker_root_str not in sys.path:
        sys.path.insert(0, worker_root_str)

    if "celery_app" not in sys.modules:
        celery_stub = ModuleType("celery_app")
        celery_stub.__dict__["celery_app"] = _NoOpCeleryApp()
        sys.modules["celery_app"] = celery_stub


def _run_task_in_thread(
    task_future: Future[object],
    module_name: str,
    task_name: str,
    task_id: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    try:
        _ensure_worker_import_context()
        task_module = import_module(module_name)
        task_func = getattr(task_module, task_name)
        result = task_func(_FakeTaskSelf(task_id), *args, **kwargs)
        task_future.set_result(result)
    except Exception as exc:
        task_future.set_exception(exc)


def dispatch_sync_task(module_name: str, task_name: str, *args: object, **kwargs: object) -> str:
    task_id = str(uuid4())
    task_future: Future[object] = Future()
    task_future.add_done_callback(_log_task_failure)

    worker_thread = threading.Thread(
        target=_run_task_in_thread,
        args=(task_future, module_name, task_name, task_id, args, dict(kwargs)),
        name=f"sync-task-{task_name}-{task_id[:8]}",
        daemon=True,
    )
    worker_thread.start()
    return task_id


def _log_task_failure(task_future: Future[object]) -> None:
    try:
        task_future.result()
    except Exception:
        logger.exception("Synchronous worker task failed")
