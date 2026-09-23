"""Behavioral optimistic-version parity, using actual migrated SQL."""

import json

import pytest
from creator_service.run_service import RunService

from .run_version_support import version_runs as version_runs

pytestmark = pytest.mark.asyncio


async def test_cancel_rejects_completion_using_pre_cancel_version(version_runs: RunService) -> None:
    # Given a worker's version snapshot before authorized cancellation.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    cancelled = await version_runs.cancel_run(run.id, workspace_id=1)
    # When that stale snapshot attempts completion through the real adapter.
    stale = await version_runs.storage.update_run(
        run.id, {"status": "completed"}, workspace_id=1, expected_version=run.version,
    )
    # Then the cancellation wins and invalidates the snapshot exactly once.
    assert stale is None
    assert cancelled.version == run.version + 1
    assert await version_runs.get_run(run.id, workspace_id=1) == cancelled


@pytest.mark.parametrize("workspace_id", [None, 1])
@pytest.mark.parametrize("updates", [
    {"status": "running"},
    {"status": "failed", "current_stage": "FAILED"},
    {"model_defaults_json": '{"script_model":"new"}'},
    {"metadata_json": '{"revision":2}'},
    {"style_preset": "cinematic"},
])
async def test_nonempty_update_increments_once_and_rejects_stale_cas(
    version_runs: RunService, workspace_id: int | None, updates: dict[str, str],
) -> None:
    # Given a fresh run and optional workspace filtering.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When an unconditional mutation succeeds.
    saved = await version_runs.storage.update_run(run.id, updates, workspace_id=workspace_id)
    # Then version advances once, fields persist, and the old CAS is rejected.
    assert saved is not None
    assert saved["version"] == run.version + 1
    assert all(saved[key] == value for key, value in updates.items())
    assert await version_runs.storage.update_run(
        run.id, {"status": "completed"}, workspace_id=workspace_id, expected_version=run.version,
    ) is None
    assert await version_runs.storage.get_run(run.id, workspace_id=workspace_id) == saved


@pytest.mark.parametrize("workspace_id", [None, 1])
async def test_model_default_merge_invalidates_stale_snapshot(
    version_runs: RunService, workspace_id: int | None,
) -> None:
    # Given defaults whose untouched key must survive an atomic merge.
    run = await version_runs.create_run(
        1, {"script_model": "old", "image_model": "keep"}, "default", workspace_id=1,
    )
    # When the actual service updates one model default.
    saved = await version_runs.update_model_defaults(
        run.id, {"script_model": "new"}, workspace_id=workspace_id,
    )
    # Then the merge preserves siblings and invalidates the earlier snapshot.
    assert saved.version == run.version + 1
    row = await version_runs.storage.get_run(run.id, workspace_id=1)
    assert row is not None
    assert json.loads(row["model_defaults_json"]) == {"script_model": "new", "image_model": "keep"}
    assert await version_runs.storage.update_run(
        run.id, {"status": "completed"}, expected_version=run.version,
    ) is None
