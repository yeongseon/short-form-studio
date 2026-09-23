from threading import Event, get_ident
from unittest.mock import MagicMock

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from shorts_api.main import app
from shorts_api.routes import admin


@pytest.mark.asyncio
async def test_redis_pipeline_leaves_request_loop_responsive(monkeypatch):
    entered, release = Event(), Event()
    loop_thread = get_ident()
    threads = []
    limiter = admin.RedisRateLimiter()
    client = MagicMock()
    limiter._redis = client

    def execute():
        threads.append(get_ident())
        entered.set()
        assert release.wait(5)
        return [1, True]

    client.pipeline.return_value.__enter__.return_value.execute.side_effect = execute
    monkeypatch.setattr(admin, "_rate_limiter", limiter)

    async def request():
        await admin.require_confirmation_and_rate_limit("yes", "test-key")

    async with anyio.create_task_group() as group:
        group.start_soon(request)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                with anyio.fail_after(5):
                    assert (await client.get("/healthz")).status_code == 200
            assert threads == [threads[0]] and threads[0] != loop_thread
        finally:
            release.set()


@pytest.mark.asyncio
async def test_admin_broker_revoke_executes_off_loop(monkeypatch):
    from creator_service import admin_service

    threads = []
    loop_thread = get_ident()
    monkeypatch.setattr(admin_service.celery_app.control, "revoke", lambda *a, **kw: threads.append(get_ident()))
    await admin_service.CeleryTaskBroker().revoke_task("task")
    assert len(threads) == 1 and threads[0] != loop_thread
