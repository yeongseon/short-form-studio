import pytest
from creator_service.run_service import RunService

from .run_version_support import version_runs as version_runs

pytestmark = pytest.mark.asyncio


async def test_empty_patch_is_a_version_checked_read_on_both_adapters(
    version_runs: RunService,
) -> None:
    # Given a run with a known version.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When the patch is empty but its version is stale.
    rejected = await version_runs.storage.update_run(
        run.id, {}, workspace_id=1, expected_version=run.version - 1,
    )
    # Then neither adapter returns a stale row or changes its version.
    assert rejected is None
    assert await version_runs.get_run(run.id, workspace_id=1) == run


async def test_empty_patch_does_not_advance_run_version(
    version_runs: RunService,
) -> None:
    # Given a run at a valid version.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When no fields are changed with a matching precondition.
    returned = await version_runs.storage.update_run(
        run.id, {}, workspace_id=1, expected_version=run.version,
    )
    # Then no new version is claimed for a read-only operation.
    assert returned is not None and returned["version"] == run.version


@pytest.mark.parametrize("column", ["version", "id", "unknown"])
async def test_invalid_update_fields_are_rejected_by_both_adapters(
    version_runs: RunService, column: str,
) -> None:
    # Given a legitimate run and a forbidden storage-owned field.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When an otherwise valid patch contains that field.
    with pytest.raises(ValueError, match="Invalid update columns"):
        await version_runs.storage.update_run(run.id, {"status": "completed", column: 500}, workspace_id=1)
    # Then state is unchanged.
    assert await version_runs.get_run(run.id, workspace_id=1) == run


@pytest.mark.parametrize("column", ["version", "id", "unknown"])
async def test_conditional_update_rejects_invalid_fields_on_both_adapters(
    version_runs: RunService, column: str,
) -> None:
    # Given a run eligible for the conditional update.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When a caller attempts to change a storage-owned or unknown column.
    with pytest.raises(ValueError, match="Invalid update columns"):
        await version_runs.storage.conditional_update_run(
            run.id, {"status": "completed", column: 500},
            expected_stages=frozenset({run.current_stage}), workspace_id=1,
        )
    # Then neither the stage nor version was changed.
    assert await version_runs.get_run(run.id, workspace_id=1) == run


async def test_empty_conditional_update_respects_rejected_status_on_both_adapters(
    version_runs: RunService,
) -> None:
    # Given a terminal run whose stage still matches the expected stage.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    await version_runs.storage.update_run(run.id, {"status": "cancelled"}, workspace_id=1)
    before = await version_runs.get_run(run.id, workspace_id=1)
    assert before is not None
    # When an empty conditional update rejects cancelled runs.
    accepted, row = await version_runs.storage.conditional_update_run(
        run.id, {}, expected_stages=frozenset({before.current_stage}),
        workspace_id=1, rejected_statuses=frozenset({"cancelled"}),
    )
    # Then no adapter reports an accepted update or increments the version.
    assert not accepted
    assert row is not None and row["version"] == before.version
