import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from creator_service import db, postgres_usage_storage
from creator_service.postgres_project_storage import PostgresProjectStorage
from creator_service.postgres_run_storage import PostgresRunStorage
from creator_service.postgres_usage_storage import PostgresUsageStorage
from creator_service.project_service import ProjectService
from creator_service.run_service import InMemoryRunStorage, RunService
from creator_service.task_dispatch_service import TaskDispatchService
from creator_service.task_tracking_service import InMemoryTaskTrackingStorage, TaskTrackingService
from creator_service.usage_service import InMemoryUsageStorage, UsageService
from pydantic import JsonValue

from .test_dispatch_port import RecordingDispatcher


@dataclass(frozen=True, slots=True)
class QuotaDispatch:
    runs: RunService
    usage: UsageService
    port: RecordingDispatcher
    tracking: TaskTrackingService
    run_id: int
    pool: asyncpg.Pool | None

    async def dispatch(self, expected_stage: str = "SUBTITLE_GENERATING") -> dict[str, JsonValue]:
        service = TaskDispatchService(self.port)
        return await service.cas_dispatch_with_rollback(
            run_id=self.run_id, expected_stages=frozenset({expected_stage}),
            target_stage="RENDER_GENERATING", dispatcher=service.dispatch_render_video,
            dispatcher_args={"run_id": self.run_id, "render_profile": "shorts_default"},
            run_service=self.runs, rollback_stage="SUBTITLE_GENERATING", rollback_restart_from=None,
            enqueue_error_detail="enqueue failed", workspace_id=1, quota_operation_type="render",
        )


@pytest_asyncio.fixture
async def quota_pool(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[asyncpg.Pool | None]:
    if request.param == "memory":
        yield None
        return
    url = os.getenv("FIRST_SHORT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL required")
    schema = f"quota_dispatch_{uuid4().hex}"
    async with asyncpg.create_pool(url, min_size=1, max_size=2) as admin:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=Path(__file__).resolve().parents[3] / "apps/api",
                env={**os.environ, "DATABASE_URL": url, "PGOPTIONS": f"-c search_path={schema}"},
                check=True, capture_output=True, timeout=60,
            )
            async with asyncpg.create_pool(
                url, min_size=1, max_size=4, server_settings={"search_path": schema},
            ) as pool:
                await pool.execute("""
                    INSERT INTO users (id, auth_subject) VALUES (1, 'quota-test');
                    INSERT INTO workspaces (id, name, slug, owner_id) VALUES (1, 'Test', 'test', 1);
                """)

                async def get_pool() -> asyncpg.Pool:
                    return pool

                monkeypatch.setattr(db, "get_pool", get_pool)
                monkeypatch.setattr(postgres_usage_storage, "get_pool", get_pool)
                yield pool
        finally:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest_asyncio.fixture
async def quota_dispatch(quota_pool: asyncpg.Pool | None, monkeypatch: pytest.MonkeyPatch) -> QuotaDispatch:
    projects = ProjectService(PostgresProjectStorage()) if quota_pool else ProjectService()
    runs = RunService(PostgresRunStorage() if quota_pool else InMemoryRunStorage())
    usage = UsageService(PostgresUsageStorage() if quota_pool else InMemoryUsageStorage())
    tracking = TaskTrackingService(InMemoryTaskTrackingStorage())
    project = await projects.create_project("quota", "idea", idea_brief="test", workspace_id=1)
    run = await runs.create_run(project.id, None, "default", current_stage="SUBTITLE_GENERATING", workspace_id=1)
    await usage.set_quota(1, monthly_tts_requests=1)
    monkeypatch.setattr("creator_service.project_service.project_service", projects)
    monkeypatch.setattr("creator_service.usage_service.usage_service", usage)
    monkeypatch.setattr("creator_service.task_tracking_service.task_tracking_service", tracking)
    return QuotaDispatch(runs, usage, RecordingDispatcher(queued=True), tracking, run.id, quota_pool)
