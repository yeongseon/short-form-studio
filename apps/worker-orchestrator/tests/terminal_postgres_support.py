import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from creator_service import db
from worker_loop import run_in_worker_loop


@pytest.fixture
def terminal_pool(monkeypatch: pytest.MonkeyPatch) -> Iterator[asyncpg.Pool]:
    url = os.getenv("FIRST_SHORT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL required")
    schema = f"terminal_{uuid4().hex}"

    async def connect_admin() -> asyncpg.Connection:
        return await asyncpg.connect(url)

    admin = run_in_worker_loop(connect_admin())
    run_in_worker_loop(admin.execute(f'CREATE SCHEMA "{schema}"'))
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3] / "apps/api",
            env={**os.environ, "DATABASE_URL": url, "PGOPTIONS": f"-c search_path={schema}"},
            check=True, capture_output=True, timeout=60,
        )

        async def connect_pool() -> asyncpg.Pool:
            return await asyncpg.create_pool(
                url, min_size=1, max_size=2, server_settings={"search_path": schema},
            )

        pool = run_in_worker_loop(connect_pool())
        try:
            run_in_worker_loop(pool.execute("""
                INSERT INTO users (id, auth_subject) VALUES (1, 'terminal-test');
                INSERT INTO workspaces (id, name, slug, owner_id) VALUES (1, 'Test', 'test', 1);
                INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1);
            """))

            async def get_pool() -> asyncpg.Pool:
                return pool

            monkeypatch.setattr(db, "get_pool", get_pool)
            yield pool
        finally:
            run_in_worker_loop(pool.close())
    finally:
        run_in_worker_loop(admin.execute(f'DROP SCHEMA "{schema}" CASCADE'))
        run_in_worker_loop(admin.close())
