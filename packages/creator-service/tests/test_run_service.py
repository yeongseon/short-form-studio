import asyncio
import json

import pytest
from creator_domain.models import ModelSelection, RunStage
from creator_service.run_service import ConflictError, InMemoryRunStorage, RunService
import creator_service.run_service as run_service_module


def test_create_run_with_model_defaults_and_style_preset() -> None:
    service = RunService(InMemoryRunStorage())

    run = asyncio.run(
        service.create_run(
            project_id=7,
            model_defaults=ModelSelection(script_model="qwen3-4b", image_model="sd15"),
            style_preset="cinematic",
        )
    )

    assert run.project_id == 7
    assert run.current_stage == RunStage.IDEA_READY.value
    assert run.status == "pending"
    assert run.style_preset == "cinematic"
    assert run.model_defaults is not None
    assert run.model_defaults.script_model == "qwen3-4b"
    assert run.model_defaults.image_model == "sd15"


def test_create_run_stores_metadata_in_metadata_json() -> None:
    storage = InMemoryRunStorage()
    service = RunService(storage)
    metadata = {"origin": "manual", "attempt": 1}

    run = asyncio.run(
        service.create_run(
            project_id=8,
            model_defaults={"script_model": "qwen3-8b"},
            style_preset="default",
            metadata=metadata,
        )
    )
    row = asyncio.run(storage.get_run(run.id))

    assert row is not None
    assert row["metadata_json"] == json.dumps(metadata)


def test_create_run_allows_custom_stage_and_status() -> None:
    service = RunService(InMemoryRunStorage())

    run = asyncio.run(
        service.create_run(
            project_id=15,
            model_defaults=None,
            style_preset="default",
            current_stage=RunStage.SCRIPT_REVIEW.value,
            status="running",
        )
    )

    assert run.current_stage == RunStage.SCRIPT_REVIEW.value
    assert run.status == "running"


def test_get_run_returns_none_for_missing() -> None:
    service = RunService(InMemoryRunStorage())

    run = asyncio.run(service.get_run(9999))

    assert run is None


def test_get_run_returns_existing_run() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=9,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    fetched = asyncio.run(service.get_run(created.id))

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.project_id == 9


def test_get_run_requires_workspace_id_for_api_context() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=9,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
            workspace_id=3,
        )
    )

    original = run_service_module._is_api_context_call
    run_service_module._is_api_context_call = lambda: True
    try:
        with pytest.raises(ValueError, match="workspace_id is required"):
            asyncio.run(service.get_run(created.id))
    finally:
        run_service_module._is_api_context_call = original


def test_get_run_allows_missing_workspace_id_for_worker_context() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=9,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
            workspace_id=3,
        )
    )

    fetched = asyncio.run(service.get_run(created.id))

    assert fetched is not None
    assert fetched.id == created.id


def test_delete_run_requires_workspace_id_for_api_context() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=9,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
            workspace_id=3,
        )
    )

    original = run_service_module._is_api_context_call
    run_service_module._is_api_context_call = lambda: True
    try:
        with pytest.raises(ValueError, match="workspace_id is required"):
            asyncio.run(service.delete_run(created.id))
    finally:
        run_service_module._is_api_context_call = original


def test_restart_run_transitions_correctly() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=10,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    restarted = asyncio.run(service.restart_run(created.id, RunStage.SCRIPT_GENERATING.value))

    assert restarted.current_stage == RunStage.SCRIPT_GENERATING.value
    assert restarted.restart_from == RunStage.SCRIPT_GENERATING.value


def test_restart_run_rejects_invalid_stage_transition() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=11,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    with pytest.raises(ValueError, match="Cannot transition"):
        asyncio.run(service.restart_run(created.id, RunStage.PUBLISHED.value))


def test_restart_run_rejects_review_stage_from_non_review_stage() -> None:
    """Verify that IDEA_READY cannot jump directly to SCRIPT_REVIEW (was incorrectly allowed)."""
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=12,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    with pytest.raises(ValueError, match="Cannot transition"):
        asyncio.run(service.restart_run(created.id, RunStage.SCRIPT_REVIEW.value))


def test_restart_run_allows_valid_review_stage_restart() -> None:
    """Verify that review stages can restart to their generating stage via TRANSITIONS."""
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=13,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    # First transition to SCRIPT_GENERATING (valid from IDEA_READY)
    stage1 = asyncio.run(service.restart_run(created.id, RunStage.SCRIPT_GENERATING.value))
    assert stage1.current_stage == RunStage.SCRIPT_GENERATING.value

    # Now manually set the stage to SCRIPT_REVIEW for testing (simulate it was reviewed)
    # We need to restart from SCRIPT_GENERATING to SCRIPT_REVIEW first
    # But since we can't directly manipulate, let's test SCRIPT_GENERATING -> SCRIPT_REVIEW transition
    # by using the fact that stage1 is now in SCRIPT_GENERATING

    # Test: from SCRIPT_REVIEW, can restart to SCRIPT_GENERATING (the generating stage)
    # We'll create a test scenario differently:
    storage = InMemoryRunStorage()
    service2 = RunService(storage)
    created2 = asyncio.run(
        service2.create_run(
            project_id=14, model_defaults={"script_model": "qwen3-4b"}, style_preset="default"
        )
    )

    # Simulate being in SCRIPT_REVIEW by manually updating storage
    asyncio.run(storage.update_run(created2.id, {"current_stage": RunStage.SCRIPT_REVIEW.value}))

    # Now restart from SCRIPT_REVIEW to SCRIPT_GENERATING should succeed (per TRANSITIONS dict)
    restarted = asyncio.run(service2.restart_run(created2.id, RunStage.SCRIPT_GENERATING.value))
    assert restarted.current_stage == RunStage.SCRIPT_GENERATING.value


def test_advance_stage_raises_conflict_for_stale_version() -> None:
    storage = InMemoryRunStorage()
    service = RunService(storage)

    created = asyncio.run(
        service.create_run(
            project_id=21,
            model_defaults=None,
            style_preset="default",
            current_stage=RunStage.IDEA_READY.value,
            workspace_id=1,
        )
    )
    asyncio.run(storage.update_run(created.id, {"current_stage": RunStage.SCRIPT_GENERATING.value}))

    original_update = storage.update_run

    async def conflicting_update_run(
        run_id: int,
        updates: dict[str, object],
        *,
        workspace_id: int | None = None,
        expected_version: int | None = None,
    ):
        if expected_version is not None:
            await original_update(run_id, {"status": "running"}, workspace_id=workspace_id)
        return await original_update(
            run_id,
            updates,
            workspace_id=workspace_id,
            expected_version=expected_version,
        )

    storage.update_run = conflicting_update_run  # type: ignore[method-assign]

    with pytest.raises(ConflictError, match="stale version"):
        asyncio.run(service.advance_stage(created.id, RunStage.SCRIPT_REVIEW.value, workspace_id=1))


def test_conditional_update_run_increments_version_and_blocks_stale_lifecycle_write() -> None:
    storage = InMemoryRunStorage()
    service = RunService(storage)

    created = asyncio.run(
        service.create_run(
            project_id=22,
            model_defaults=None,
            style_preset="default",
            current_stage=RunStage.SCRIPT_REVIEW.value,
            workspace_id=1,
        )
    )

    ok, updated = asyncio.run(
        storage.conditional_update_run(
            created.id,
            {"current_stage": RunStage.SCRIPT_GENERATING.value},
            frozenset({RunStage.SCRIPT_REVIEW.value}),
        )
    )
    assert ok is True
    assert updated is not None
    assert updated["version"] == 1

    stale = asyncio.run(
        storage.update_run(
            created.id,
            {"status": "cancelled"},
            workspace_id=1,
            expected_version=0,
        )
    )
    assert stale is None


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("restart_run", (RunStage.SCRIPT_GENERATING.value,)),
        ("advance_stage", (RunStage.SCRIPT_GENERATING.value,)),
        ("stop_run", ()),
        ("resume_run", ()),
    ],
)
def test_lifecycle_cas_miss_raises_not_found_when_run_deleted(
    method_name: str, args: tuple[str, ...]
) -> None:
    storage = InMemoryRunStorage()
    service = RunService(storage)

    current_stage = (
        RunStage.SCRIPT_GENERATING.value if method_name == "stop_run" else RunStage.IDEA_READY.value
    )
    status = "cancelled" if method_name == "resume_run" else "pending"
    created = asyncio.run(
        service.create_run(
            project_id=30,
            model_defaults=None,
            style_preset="default",
            current_stage=current_stage,
            status=status,
            workspace_id=5,
        )
    )

    original_update = storage.update_run

    async def deleting_update_run(
        run_id: int,
        updates: dict[str, object],
        *,
        workspace_id: int | None = None,
        expected_version: int | None = None,
    ):
        if expected_version is not None:
            storage._rows.pop(run_id, None)
            return None
        return await original_update(
            run_id,
            updates,
            workspace_id=workspace_id,
            expected_version=expected_version,
        )

    storage.update_run = deleting_update_run  # type: ignore[method-assign]
    method = getattr(service, method_name)

    with pytest.raises(ValueError, match=f"Run {created.id} not found"):
        asyncio.run(method(created.id, *args, workspace_id=5))


def test_restart_run_cas_miss_stale_still_raises_conflict() -> None:
    storage = InMemoryRunStorage()
    service = RunService(storage)

    created = asyncio.run(
        service.create_run(
            project_id=31,
            model_defaults=None,
            style_preset="default",
            current_stage=RunStage.IDEA_READY.value,
            workspace_id=8,
        )
    )

    original_update = storage.update_run

    async def stale_update_run(
        run_id: int,
        updates: dict[str, object],
        *,
        workspace_id: int | None = None,
        expected_version: int | None = None,
    ):
        if expected_version is not None:
            await original_update(run_id, {"status": "running"}, workspace_id=workspace_id)
        return await original_update(
            run_id,
            updates,
            workspace_id=workspace_id,
            expected_version=expected_version,
        )

    storage.update_run = stale_update_run  # type: ignore[method-assign]

    with pytest.raises(ConflictError, match="stale version"):
        asyncio.run(
            service.restart_run(created.id, RunStage.SCRIPT_GENERATING.value, workspace_id=8)
        )


def test_create_run_raises_conflict_when_project_is_deleting() -> None:
    """Atomic write-boundary guard: create_run must refuse if the project
    has been marked 'deleting' between the auth check and the INSERT.

    This tests the service-layer guard (which delegates to storage).
    In production, PostgresRunStorage enforces this atomically via SQL.
    For InMemoryRunStorage we simulate by setting a project_status_checker.
    """
    storage = InMemoryRunStorage()
    # Simulate: project 7 is being deleted
    storage.project_status_checker = lambda pid: "deleting"
    service = RunService(storage)

    with pytest.raises(ConflictError, match="(?i)delet"):
        asyncio.run(
            service.create_run(
                project_id=7,
                model_defaults=None,
                style_preset="default",
                workspace_id=1,
            )
        )


def test_postgres_create_run_query_includes_workspace_id_and_row_lock():
    """The INSERT...SELECT CTE must scope by workspace_id and use FOR UPDATE."""
    import ast
    import textwrap
    from pathlib import Path

    src = Path("packages/creator-service/creator_service/postgres_run_storage.py").read_text()
    tree = ast.parse(src)

    # Find the create_run method and extract the SQL string
    sql_found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value.lower()
            if "insert into creator_runs" in val and "creator_projects" in val:
                sql_found = val
                break

    assert sql_found is not None, "Could not find INSERT...SELECT query in postgres_run_storage.py"

    # Must use CTE with FOR UPDATE
    assert "for update" in sql_found, "Query must use FOR UPDATE to lock the project row"

    # Must scope by workspace_id in the CTE WHERE clause (not just anywhere in the query)
    import re as _re
    cte_match = _re.search(r"with\s+\w+\s+as\s*\((.+?)\)", sql_found, _re.DOTALL)
    assert cte_match is not None, "Could not extract CTE body from query"
    cte_body = cte_match.group(1)
    assert "workspace_id" in cte_body, "CTE WHERE clause must scope by workspace_id"

    # Must be a CTE (WITH ... AS)
    assert "with " in sql_found and " as" in sql_found, "Query must use a CTE (WITH ... AS)"
