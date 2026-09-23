import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import pytest
from httpx import AsyncClient
from shorts_api.auth import _current_user_ctx
from shorts_api.lifecycle import shutdown_state

from tests.auth_lookup_support import AuthDatabase, auth_db  # noqa: F401
from tests.middleware_app_support import middleware_app, middleware_client  # noqa: F401


@pytest.mark.parametrize("cancel", [False, True])
async def test_auth_lookup_is_counted_until_completion_or_cancellation(
    middleware_client: AsyncClient, auth_db: AuthDatabase, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, cancel: bool,
) -> None:
    # Given: pause a real auth lookup at pool acquisition without sleeps.
    entered = anyio.Event()
    release = anyio.Event()
    counts: list[int] = []
    caplog.set_level(logging.INFO, logger="shorts_api.app_factory")

    @asynccontextmanager
    async def acquire() -> AsyncIterator[AuthDatabase]:
        entered.set()
        await release.wait()
        yield auth_db

    monkeypatch.setattr(auth_db, "acquire", acquire)

    async def request() -> None:
        response = await middleware_client.get("/api/creator/projects", headers={"X-API-Key": "invalid"})
        assert response.status_code == 401

    # When
    with anyio.fail_after(5):
        async with anyio.create_task_group() as group:
            group.start_soon(request)
            await entered.wait()
            counts.append(shutdown_state.inflight_requests)
            if cancel:
                group.cancel_scope.cancel()
            else:
                release.set()
    # Then
    assert counts == [1]
    assert shutdown_state.inflight_requests == 0
    assert _current_user_ctx.get() is None
    records = [r for r in caplog.records if r.name == "shorts_api.app_factory"]
    assert len(records) == 1
    assert (records[0].user_id, records[0].key_id, records[0].workspace_id) == (None, None, None)
