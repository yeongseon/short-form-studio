"""Per-process long-lived event loop for Celery workers.

Celery workers previously called ``asyncio.run()`` per task, which creates and
destroys an event loop each time.  This forced asyncpg to tear down and
re-create its connection pool on every task invocation -- expensive and
unnecessary.

This module provides a **per-process persistent event loop** that is:

1. Created once via the ``worker_process_init`` Celery signal.
2. Reused across all tasks via ``run_in_worker_loop(coro)``.
3. Cleaned up (including closing the DB pool) via ``worker_process_shutdown``.

The pool in ``creator_service.db`` is loop-aware: as long as the event loop
stays the same, it reuses the existing pool.  By keeping a single loop alive
for the lifetime of the worker process, we get true connection pool reuse.

**Task isolation**: After each ``run_in_worker_loop()`` call, any pending
background tasks on the loop are cancelled and async generators are shut down.
This preserves the isolation guarantees that ``asyncio.run()`` provided.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Coroutine, TypeVar

from celery.signals import worker_process_init, worker_process_shutdown

logger = logging.getLogger(__name__)

T = TypeVar("T")

_worker_loop: asyncio.AbstractEventLoop | None = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the per-process persistent event loop.

    Falls back to creating a new loop if called outside a Celery worker
    context (e.g. in tests or the reconciler beat task).
    """
    global _worker_loop
    if _worker_loop is not None and not _worker_loop.is_closed():
        return _worker_loop
    # Fallback: create a loop (useful for beat tasks / tests)
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _cancel_pending_tasks(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel and drain any pending tasks on the loop.

    This restores the isolation guarantee that ``asyncio.run()`` provided:
    background tasks from one Celery job must not leak into the next.
    """
    pending = asyncio.all_tasks(loop)
    if not pending:
        return
    for task in pending:
        task.cancel()
    # Give cancelled tasks a chance to handle CancelledError
    with contextlib.suppress(Exception):
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))


def run_in_worker_loop(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on the per-process event loop.

    Unlike ``asyncio.run()``, this does NOT create or destroy the event loop,
    so asyncpg pools (and any other loop-bound resources) persist across calls.

    After the coroutine completes (or raises), any orphaned background tasks
    are cancelled and async generators are shut down to maintain per-task
    isolation.
    """
    loop = get_worker_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        # Restore asyncio.run()-equivalent cleanup without closing the loop
        _cancel_pending_tasks(loop)
        with contextlib.suppress(Exception):
            loop.run_until_complete(loop.shutdown_asyncgens())


@worker_process_init.connect
def _init_worker_loop(**_kwargs: object) -> None:
    """Create the per-process event loop when a Celery worker process starts."""
    global _worker_loop
    # Close any pre-existing fallback loop to prevent leaks
    if _worker_loop is not None and not _worker_loop.is_closed():
        with contextlib.suppress(Exception):
            _worker_loop.close()
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    logger.info("Per-process event loop created for worker")


@worker_process_shutdown.connect
def _shutdown_worker_loop(**_kwargs: object) -> None:
    """Close the DB pool and event loop when the worker process exits."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        return
    try:
        from creator_service.db import close_pool
        _worker_loop.run_until_complete(close_pool())
        logger.info("DB connection pool closed during worker shutdown")
    except Exception:
        logger.warning("Failed to close DB pool during worker shutdown", exc_info=True)
    try:
        _worker_loop.close()
        logger.info("Per-process event loop closed")
    except Exception:
        logger.warning("Failed to close event loop during worker shutdown", exc_info=True)
    _worker_loop = None


def reset_worker_loop() -> None:
    """Reset the worker loop state. For testing only."""
    global _worker_loop
    if _worker_loop is not None and not _worker_loop.is_closed():
        _worker_loop.close()
    _worker_loop = None
