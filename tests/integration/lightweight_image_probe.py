# /// script
# requires-python = ">=3.12"
# dependencies = ["anyio", "httpx", "celery", "asyncpg"]
# ///
"""Run inside the API runtime image: python /probe/lightweight_image_probe.py."""

import os
from functools import partial
from threading import Event, get_ident

import anyio
from celery import Celery
from creator_domain.task_dispatch import TaskSubmission
from creator_service import db
from creator_service.blocking_io import run_blocking
from httpx import ASGITransport, AsyncClient
from shorts_api.main import app
from shorts_api.task_dispatch_adapter import ApplicationTaskDispatcher
from tasks.task_runner import run_in_worker_loop


async def main() -> None:
    release = Event()
    entered = Event()
    main_thread = get_ident()
    results = []
    queue = Celery("image-probe", broker=os.environ["PROBE_REDIS_URL"])

    @queue.task(bind=True)
    def render(self, run_id: int, render_profile: str):
        assert get_ident() != main_thread

        async def operation():
            assert await db.fetch_one("SELECT 812 AS value") == {"value": 812}
            entered.set()
            assert release.wait(10), "health did not release lightweight execution"
            assert await db.fetch_one("SELECT 813 AS value") == {"value": 813}
            return {"status": "success", "run_id": run_id, "profile": render_profile}

        results.append(run_in_worker_loop(operation()))

    adapter = ApplicationTaskDispatcher()
    adapter._load_task = lambda _: render
    submission = TaskSubmission("render_video", 812, (812,), {"render_profile": "vertical"}, "probe-812")
    api_pool = await db.get_pool()
    returned = []

    async def dispatch():
        returned.append(await run_blocking(partial(adapter.dispatch, submission)))

    async with anyio.create_task_group() as group:
        group.start_soon(dispatch)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 10)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://image") as client:
                with anyio.fail_after(5):
                    assert (await client.get("/healthz")).status_code == 200
                    assert await db.get_pool() is api_pool
                    assert await db.fetch_one("SELECT 1 AS healthy") == {"healthy": 1}
            assert not returned and not results
        finally:
            release.set()
    assert returned == ["probe-812"]
    assert results == [{"status": "success", "run_id": 812, "profile": "vertical"}]
    assert await db.get_pool() is api_pool
    await db.close_pool()
    os.environ["REDIS_URL"] = os.environ["PROBE_REDIS_URL"]
    assert await run_blocking(partial(adapter.dispatch, submission)) == "probe-812"
    print("PASS: image lightweight task + concurrent HTTP health + real DB ownership + Redis publication")


if __name__ == "__main__":
    anyio.run(main)
