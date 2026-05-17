from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import asyncpg

# Pool singleton with event-loop awareness.
# Celery workers call asyncio.run() per task, creating a new event loop each
# time.  A pool created on a previous loop is stale and unusable.  We track
# which loop owns the current pool and transparently recreate it when the
# loop changes.
_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None
_pool_init_lock: asyncio.Lock | None = None
_pool_init_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_init_lock() -> asyncio.Lock:
    """Return an asyncio.Lock bound to the current event loop.
    
    Creates a new lock when the event loop changes (e.g. Celery worker
    starts a new asyncio.run() per task).
    """
    global _pool_init_lock, _pool_init_lock_loop
    current_loop = asyncio.get_running_loop()
    if _pool_init_lock is None or _pool_init_lock_loop is not current_loop:
        _pool_init_lock = asyncio.Lock()
        _pool_init_lock_loop = current_loop
    return _pool_init_lock

async def get_pool() -> asyncpg.Pool:
    global _pool, _pool_loop
    current_loop = asyncio.get_running_loop()

    # Fast path – pool exists and belongs to the current loop.
    if _pool is not None and _pool_loop is current_loop:
        return _pool

    # Slow path – need to create (or recreate) the pool.
    async with _get_init_lock():
        # Double-check after acquiring lock.
        if _pool is not None and _pool_loop is current_loop:
            return _pool

        # Close stale pool from a previous event loop (best-effort).
        if _pool is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(_pool.close(), timeout=2.0)
            _pool = None
            _pool_loop = None

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for Postgres storage")

        _pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
        _pool_loop = current_loop
        return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool. Call on app shutdown."""
    global _pool, _pool_loop
    if _pool is not None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(_pool.close(), timeout=5.0)
        _pool = None
        _pool_loop = None


async def fetch_one(query: str, *args: Any) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(query, *args)
    if row is None:
        return None
    return dict(row)


async def fetch_all(query: str, *args: Any) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(query, *args)
    return [dict(row) for row in rows]


async def execute(query: str, *args: Any) -> str:
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.execute(query, *args)


@contextlib.asynccontextmanager
async def transaction():
    """Yield an asyncpg connection inside an explicit transaction.

    Usage::

        async with transaction() as conn:
            rows = await conn.fetch("SELECT ... FOR UPDATE SKIP LOCKED")
            # rows remain locked until the transaction commits
            await conn.execute("DELETE ...")
    """
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            yield connection
