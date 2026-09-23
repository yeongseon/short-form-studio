"""Isolated migrated PostgreSQL and memory stores for version contracts."""

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import anyio
import asyncpg
import pytest
import pytest_asyncio
from creator_service import db
from creator_service.postgres_run_storage import PostgresRunStorage
from creator_service.run_service import InMemoryRunStorage, RunService


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def version_runs(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[RunService]:
    if request.param == "memory":
        yield RunService(InMemoryRunStorage())
        return
    url = os.getenv("FIRST_SHORT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL required")
    schema = f"run_version_{uuid4().hex}"
    async with asyncpg.create_pool(url, min_size=1, max_size=2) as admin:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            await anyio.run_process(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=Path(__file__).resolve().parents[3] / "apps/api",
                env={**os.environ, "DATABASE_URL": url, "PGOPTIONS": f"-c search_path={schema}"},
            )
            async with asyncpg.create_pool(
                url, min_size=2, max_size=4,
                command_timeout=10, server_settings={"search_path": schema},
            ) as pool:
                await pool.execute("""
                    INSERT INTO users (id, auth_subject) VALUES (1, 'version-test');
                    INSERT INTO workspaces (id, name, slug, owner_id)
                    VALUES (1, 'Test', 'test', 1), (2, 'Other', 'other', 1);
                    INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1);
                """)

                async def get_pool() -> asyncpg.Pool:
                    return pool

                monkeypatch.setattr(db, "get_pool", get_pool)
                yield RunService(PostgresRunStorage())
        finally:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
