from __future__ import annotations

import asyncio
import os
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is not None:
            return _pool

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for Postgres storage")

        _pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
        return _pool


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
