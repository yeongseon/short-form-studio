import json

import anyio
import pytest
from creator_service.run_service import RunService

from .run_version_support import version_runs as version_runs

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("workspace_id", [None, 1])
async def test_cas_updates_once_when_version_matches(
    version_runs: RunService, workspace_id: int | None,
) -> None:
    # Given the current version of a run.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When a matching CAS updates two fields.
    saved = await version_runs.storage.update_run(
        run.id, {"status": "running", "current_stage": "SCRIPT_GENERATING"},
        expected_version=run.version, workspace_id=workspace_id,
    )
    # Then both fields change with exactly one increment, persisted by the adapter.
    assert saved is not None
    assert (saved["status"], saved["current_stage"], saved["version"]) == (
        "running", "SCRIPT_GENERATING", run.version + 1,
    )
    assert await version_runs.storage.get_run(run.id) == saved


async def test_only_one_writer_wins_when_versions_match(version_runs: RunService) -> None:
    # Given two writers holding the same snapshot, released by one event.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    ready = anyio.Event()
    outcomes: list[str] = []

    async def compete(style: str) -> None:
        await ready.wait()
        saved = await version_runs.storage.update_run(
            run.id, {"style_preset": style}, workspace_id=1, expected_version=run.version,
        )
        if saved is not None:
            outcomes.append(style)

    # When the two adapter calls contend for the same row version.
    with anyio.fail_after(15):
        async with anyio.create_task_group() as group:
            group.start_soon(compete, "first")
            group.start_soon(compete, "second")
            ready.set()
    # Then one wins and the loser makes no second version change.
    assert len(outcomes) == 1
    saved = await version_runs.get_run(run.id, workspace_id=1)
    assert saved is not None
    assert saved.version == run.version + 1
    assert saved.style_preset == outcomes[0]


async def test_unconditional_writers_each_increment_when_contending(version_runs: RunService) -> None:
    # Given two independent mutations released together.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    ready = anyio.Event()
    versions: list[int] = []

    async def compete(updates: dict[str, str]) -> None:
        await ready.wait()
        saved = await version_runs.storage.update_run(run.id, updates, workspace_id=1)
        assert saved is not None
        versions.append(saved["version"])

    # When both writes are accepted without a CAS precondition.
    with anyio.fail_after(15):
        async with anyio.create_task_group() as group:
            group.start_soon(compete, {"style_preset": "new"})
            group.start_soon(compete, {"status": "running"})
            ready.set()
    # Then neither version increment is lost.
    assert sorted(versions) == [run.version + 1, run.version + 2]
    saved = await version_runs.get_run(run.id, workspace_id=1)
    assert saved is not None
    assert (saved.version, saved.status, saved.style_preset) == (run.version + 2, "running", "new")


@pytest.mark.parametrize("status", ["running", "cancelled", "completed", "failed"])
async def test_conditional_status_guard_controls_mutation_and_version(
    version_runs: RunService, status: str,
) -> None:
    # Given an eligible stage with a possibly terminal status.
    run = await version_runs.create_run(
        1, None, "default", workspace_id=1, current_stage="SCRIPT_GENERATING", status=status,
    )
    # When the same status guard used by the common runner is applied.
    applied, row = await version_runs.storage.conditional_update_run(
        run.id, {"current_stage": "SCRIPT_REVIEW"}, frozenset({"SCRIPT_GENERATING"}),
        workspace_id=1, rejected_statuses=frozenset({"cancelled", "completed", "failed"}),
    )
    # Then accepted writes increment once; rejected writes preserve the version.
    assert applied == (status == "running")
    assert row is not None
    assert row["version"] == run.version + int(applied)
    assert row["current_stage"] == ("SCRIPT_REVIEW" if applied else "SCRIPT_GENERATING")


async def test_conditional_stage_miss_preserves_snapshot(version_runs: RunService) -> None:
    # Given a run outside the expected stage.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When a stale stage update is attempted.
    applied, row = await version_runs.storage.conditional_update_run(
        run.id, {"status": "running"}, frozenset({"SCRIPT_GENERATING"}), workspace_id=1,
    )
    # Then no version or state changes.
    assert applied is False
    assert row is not None and row["version"] == run.version
    assert await version_runs.get_run(run.id, workspace_id=1) == run


async def test_concurrent_model_merges_preserve_both_keys_and_versions(version_runs: RunService) -> None:
    # Given two model selections to merge into the same run.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    ready = anyio.Event()
    versions: list[int] = []

    async def merge(updates: dict[str, str]) -> None:
        await ready.wait()
        saved = await version_runs.update_model_defaults(run.id, updates, workspace_id=1)
        versions.append(saved.version)

    # When both service calls execute concurrently against the real adapters.
    with anyio.fail_after(15):
        async with anyio.create_task_group() as group:
            group.start_soon(merge, {"script_model": "script-new"})
            group.start_soon(merge, {"image_model": "image-new"})
            ready.set()
    # Then atomic merge and version increments both survive contention.
    assert sorted(versions) == [run.version + 1, run.version + 2]
    saved = await version_runs.storage.get_run(run.id, workspace_id=1)
    assert saved is not None
    assert json.loads(saved["model_defaults_json"]) == {
        "script_model": "script-new", "image_model": "image-new",
    }
    assert saved["version"] == run.version + 2
