import asyncpg
import pytest
from creator_service.run_service import RunService

from .run_version_support import version_runs as version_runs

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("run_id,workspace_id", [(999, 1), (1, 2)])
async def test_unconditional_foreign_or_missing_run_is_not_found(
    version_runs: RunService, run_id: int, workspace_id: int,
) -> None:
    # Given a run in a different authorized scope, or a nonexistent ID.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When cancellation is attempted outside the run scope.
    with pytest.raises(ValueError, match="not found"):
        await version_runs.cancel_run(run_id, workspace_id=workspace_id)
    # Then the real run stays unchanged.
    assert await version_runs.get_run(run.id, workspace_id=1) == run


@pytest.mark.parametrize("version_runs", ["postgres"], indirect=True)
@pytest.mark.parametrize("run_id,workspace_id", [(999, 1), (1, 2)])
async def test_postgres_cas_scope_miss_returns_none(
    version_runs: RunService, run_id: int, workspace_id: int,
) -> None:
    # Given a matching version but an ID or workspace outside the target scope.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When the scoped CAS runs.
    result = await version_runs.storage.update_run(
        run_id, {"status": "completed"}, workspace_id=workspace_id, expected_version=run.version,
    )
    # Then the existing PostgreSQL miss contract is preserved without mutation.
    assert result is None
    assert await version_runs.get_run(run.id, workspace_id=1) == run


@pytest.mark.parametrize("version_runs", ["postgres"], indirect=True)
@pytest.mark.parametrize("column", ["version", "id", "unknown", "status = 'completed' --"])
@pytest.mark.parametrize("expected_version", [None, 0])
async def test_postgres_rejects_user_version_and_invalid_field_overrides(
    version_runs: RunService, column: str, expected_version: int | None,
) -> None:
    # Given untrusted field names including the storage-owned version column.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When a valid status change is mixed with a forbidden field.
    with pytest.raises(ValueError, match="Invalid update columns"):
        await version_runs.storage.update_run(
            run.id, {"status": "completed", column: 500},
            workspace_id=1, expected_version=expected_version,
        )
    # Then the entire update is rejected before changing persisted state.
    assert await version_runs.get_run(run.id, workspace_id=1) == run


@pytest.mark.parametrize("version_runs", ["memory"], indirect=True)
async def test_memory_rejects_caller_version_override(version_runs: RunService) -> None:
    # Given a valid run with a storage-owned version.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When a caller tries to select an arbitrary version.
    with pytest.raises(ValueError, match="Invalid update columns"):
        await version_runs.storage.update_run(run.id, {"version": 500}, workspace_id=1)
    # Then no version or state changes.
    assert await version_runs.get_run(run.id, workspace_id=1) == run


@pytest.mark.parametrize("version_runs", ["postgres"], indirect=True)
async def test_postgres_empty_update_checks_version(version_runs: RunService) -> None:
    # Given an empty patch, which is historically a scoped read in PostgreSQL.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When no fields are supplied with a stale expected version.
    saved = await version_runs.storage.update_run(run.id, {}, workspace_id=1, expected_version=-1)
    # Then stale reads do not masquerade as accepted updates.
    assert saved is None
    assert await version_runs.get_run(run.id, workspace_id=1) == run


async def test_model_default_scope_miss_preserves_version(version_runs: RunService) -> None:
    # Given a run belonging to workspace 1.
    run = await version_runs.create_run(1, {"script_model": "keep"}, "default", workspace_id=1)
    # When workspace 2 tries to merge defaults.
    with pytest.raises(ValueError, match="not found"):
        await version_runs.update_model_defaults(run.id, {"script_model": "new"}, workspace_id=2)
    # Then no fields or version change.
    assert await version_runs.get_run(run.id, workspace_id=1) == run


@pytest.mark.parametrize("version_runs", ["postgres"], indirect=True)
async def test_database_rejection_rolls_back_version_with_fields(version_runs: RunService) -> None:
    # Given a valid run and a status that violates the migrated CHECK constraint.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When PostgreSQL rejects the actual UPDATE statement.
    with pytest.raises(asyncpg.CheckViolationError):
        await version_runs.storage.update_run(
            run.id, {"current_stage": "SCRIPT_REVIEW", "status": "not-a-status"}, workspace_id=1,
        )
    # Then neither the fields nor the version partially commits.
    assert await version_runs.get_run(run.id, workspace_id=1) == run


@pytest.mark.parametrize("version_runs", ["memory"], indirect=True)
async def test_memory_empty_update_is_read_only(version_runs: RunService) -> None:
    # Given an empty patch in the existing memory adapter.
    run = await version_runs.create_run(1, None, "default", workspace_id=1)
    # When its current version matches the CAS precondition.
    saved = await version_runs.storage.update_run(run.id, {}, expected_version=run.version)
    # Then the version is not advanced by an empty patch.
    assert saved is not None and saved["version"] == run.version
