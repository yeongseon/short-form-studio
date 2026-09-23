from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest
from shorts_api.routes import scene_image_dispatch as routes
from shorts_api.schemas.creator_visuals import GenerateSceneImageRequest


@pytest.mark.asyncio
async def test_scene_dispatch_keeps_loop_alive_until_tracking(monkeypatch):
    entered, release = Event(), Event()
    threads = []
    main_thread = get_ident()

    def dispatch(**kwargs):
        threads.append(get_ident())
        entered.set()
        assert release.wait(5)
        return "scene-task"

    monkeypatch.setattr(routes, "validate_model_key", lambda *a, **kw: None)
    monkeypatch.setattr(routes, "_enforce_run_quota", AsyncMock(return_value=1))
    monkeypatch.setattr(routes, "dispatch_generate_scene_image", dispatch)
    tracking = AsyncMock()
    monkeypatch.setattr(routes.task_tracking_service, "record_task_queued", tracking)
    results = []

    async def request():
        results.append(await routes.generate_scene_image_endpoint(
            1, "scene-1", GenerateSceneImageRequest(),
            (SimpleNamespace(workspace_id=1), SimpleNamespace(current_stage="VISUAL_ASSET_REVIEW")),
        ))

    async with anyio.create_task_group() as group:
        group.start_soon(request)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            tracking.assert_not_awaited()
            assert threads[0] != main_thread
        finally:
            release.set()
    assert results[0]["task_id"] == "scene-task"
    tracking.assert_awaited_once_with(1, "generate_scene_image", "scene-task")
