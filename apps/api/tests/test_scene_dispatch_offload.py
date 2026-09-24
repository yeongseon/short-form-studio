from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import anyio
import pytest
from fastapi import HTTPException
from shorts_api.routes import scene_image_dispatch as routes
from shorts_api.schemas.creator_visuals import GenerateSceneImageRequest


@pytest.mark.asyncio
async def test_scene_dispatch_keeps_loop_alive_until_tracking(monkeypatch):
    entered, release = Event(), Event()
    threads = []
    main_thread = get_ident()

    owners = []

    async def reserve(_workspace_id, _operation_type, owner_id):
        owners.append(owner_id)
        return True, "ok"

    def dispatch(**kwargs):
        threads.append(get_ident())
        entered.set()
        assert release.wait(5)
        return kwargs["task_id"]

    monkeypatch.setattr(routes, "validate_model_key", lambda *a, **kw: None)
    monkeypatch.setattr(routes, "_enforce_run_quota", AsyncMock(return_value=1))
    monkeypatch.setattr(routes.run_service, "get_run", AsyncMock(return_value=SimpleNamespace(status="running")))
    monkeypatch.setattr(routes, "reserve_owned_quota", reserve, raising=False)
    monkeypatch.setattr(routes, "dispatch_generate_scene_image", dispatch)
    tracking = AsyncMock()
    monkeypatch.setattr(routes.task_tracking_service, "record_task_pending", tracking)
    monkeypatch.setattr(routes.task_tracking_service, "promote_pending_to_queued", AsyncMock())
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
            tracking.assert_awaited_once()
            assert threads[0] != main_thread
        finally:
            release.set()
    assert UUID(results[0]["task_id"]).version == 4
    assert owners == [results[0]["task_id"]]
    tracking.assert_awaited_once_with(1, "generate_scene_image", results[0]["task_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled", "tracking_failed"])
async def test_scene_dispatch_releases_only_its_owner_on_failure(monkeypatch, status):
    # Given a dispatch that publishes a preassigned ID, and another outstanding owner.
    owners = []
    cancelled = []
    revoked = []
    monkeypatch.setattr(routes, "validate_model_key", lambda *a, **kw: None)
    monkeypatch.setattr(routes, "_enforce_run_quota", AsyncMock(return_value=1))

    async def reserve(_workspace_id, _operation_type, owner_id):
        owners.append(owner_id)
        return True, "ok"

    async def cancel(owner_id):
        cancelled.append(owner_id)
        return True

    monkeypatch.setattr(routes, "reserve_owned_quota", reserve)
    monkeypatch.setattr(routes, "cancel_owned_quota_reservation", cancel)
    monkeypatch.setattr(routes, "dispatch_generate_scene_image", lambda **kwargs: kwargs["task_id"])
    monkeypatch.setattr(routes, "run_control", lambda callback: anyio.to_thread.run_sync(callback))
    monkeypatch.setattr(routes.task_dispatch_service.dispatcher, "cancel", lambda task_id: revoked.append(task_id))
    monkeypatch.setattr(routes.task_tracking_service, "record_task_pending", AsyncMock())
    monkeypatch.setattr(
        routes.task_tracking_service, "promote_pending_to_queued",
        AsyncMock(side_effect=OSError("tracking failed") if status == "tracking_failed" else None),
    )
    monkeypatch.setattr(routes.task_tracking_service, "mark_tasks_revoked", AsyncMock())
    monkeypatch.setattr(
        routes.run_service, "get_run",
        AsyncMock(return_value=SimpleNamespace(status="cancelled")),
    )

    # When tracking fails or the run is cancelled after publishing.
    with pytest.raises(HTTPException) as error:
        await routes.generate_scene_image_endpoint(
            1, "scene-1", GenerateSceneImageRequest(),
            (SimpleNamespace(workspace_id=1), SimpleNamespace(current_stage="VISUAL_ASSET_REVIEW")),
        )

    # Then only the dispatched task ID is revoked and released.
    assert error.value.status_code == (409 if status == "cancelled" else 503)
    assert len(owners) == 1
    assert cancelled == revoked == owners
