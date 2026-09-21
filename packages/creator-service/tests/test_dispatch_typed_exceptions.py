"""Tests that task_dispatch_service raises typed domain exceptions, not HTTPException.

Verifies that cas_dispatch_with_rollback raises NotFoundError, ConflictError,
QuotaExceededError, ServiceUnavailableError, and ValidationError instead of
fastapi.HTTPException.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from creator_domain.exceptions import (
    ConflictError,
    NotFoundError,
    QuotaExceededError,
    ServiceUnavailableError,
    ValidationError,
)
from creator_service.task_dispatch_service import TaskDispatchService


def _make_run(run_id: int = 1, status: str = "active", project_id: int = 10) -> SimpleNamespace:
    return SimpleNamespace(id=run_id, status=status, project_id=project_id)


def _make_project(project_id: int = 10, workspace_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=project_id, workspace_id=workspace_id)


def _make_run_service(
    run: SimpleNamespace | None = None,
    cas_result: tuple[bool, dict[str, Any] | None] = (True, {"current_stage": "GENERATING"}),
) -> SimpleNamespace:
    async def get_run(run_id: int, workspace_id: int | None = None) -> SimpleNamespace | None:
        return run

    storage = AsyncMock()
    storage.conditional_update_run = AsyncMock(return_value=cas_result)
    return SimpleNamespace(get_run=get_run, storage=storage)


class TestCasDispatchRaisesNotFound:
    """cas_dispatch_with_rollback raises NotFoundError for missing runs/projects."""

    @pytest.mark.asyncio
    async def test_pre_check_run_not_found(self) -> None:
        svc = TaskDispatchService()
        run_service = _make_run_service(run=None)

        with pytest.raises(NotFoundError, match="Run not found"):
            await svc.cas_dispatch_with_rollback(
                run_id=999,
                expected_stages=frozenset({"IDLE"}),
                target_stage="GENERATING",
                dispatcher=lambda **kw: "task-id",
                dispatcher_args={},
                run_service=run_service,
                rollback_stage="IDLE",
                rollback_restart_from=None,
                enqueue_error_detail="Enqueue failed",
            )

    @pytest.mark.asyncio
    async def test_cas_update_run_not_found(self) -> None:
        """CAS update returns (False, None) → run deleted mid-flight."""
        run = _make_run()
        run_service = _make_run_service(run=run, cas_result=(False, None))

        svc = TaskDispatchService()
        with pytest.raises(NotFoundError, match="Run not found"):
            await svc.cas_dispatch_with_rollback(
                run_id=1,
                expected_stages=frozenset({"IDLE"}),
                target_stage="GENERATING",
                dispatcher=lambda **kw: "task-id",
                dispatcher_args={},
                run_service=run_service,
                rollback_stage="IDLE",
                rollback_restart_from=None,
                enqueue_error_detail="Enqueue failed",
            )

    @pytest.mark.asyncio
    async def test_quota_check_project_not_found(self) -> None:
        """Project lookup during quota check returns None → NotFoundError."""
        run = _make_run()
        run_service = _make_run_service(run=run)

        svc = TaskDispatchService()
        with patch(
            "creator_service.task_dispatch_service.import_module"
        ) as mock_import:
            project_svc = SimpleNamespace(
                get_project=AsyncMock(return_value=None),
            )
            usage_mod = SimpleNamespace(
                check_workspace_quota=AsyncMock(return_value=(True, None)),
            )

            def side_effect(name: str) -> Any:
                if "project_service" in name:
                    return SimpleNamespace(project_service=project_svc)
                if "usage_service" in name:
                    return usage_mod
                return SimpleNamespace()

            mock_import.side_effect = side_effect

            with pytest.raises(NotFoundError, match="Project not found"):
                await svc.cas_dispatch_with_rollback(
                    run_id=1,
                    expected_stages=frozenset({"IDLE"}),
                    target_stage="GENERATING",
                    dispatcher=lambda **kw: "task-id",
                    dispatcher_args={},
                    run_service=run_service,
                    rollback_stage="IDLE",
                    rollback_restart_from=None,
                    enqueue_error_detail="Enqueue failed",
                    quota_operation_type="generate_script",
                    workspace_id=None,
                )


class TestCasDispatchRaisesConflict:
    """cas_dispatch_with_rollback raises ConflictError for stage/cancel conflicts."""

    @pytest.mark.asyncio
    async def test_cancelled_run_raises_conflict(self) -> None:
        run = _make_run(status="cancelled")
        run_service = _make_run_service(run=run)

        svc = TaskDispatchService()
        with pytest.raises(ConflictError, match="cancelled"):
            await svc.cas_dispatch_with_rollback(
                run_id=1,
                expected_stages=frozenset({"IDLE"}),
                target_stage="GENERATING",
                dispatcher=lambda **kw: "task-id",
                dispatcher_args={},
                run_service=run_service,
                rollback_stage="IDLE",
                rollback_restart_from=None,
                enqueue_error_detail="Enqueue failed",
            )

    @pytest.mark.asyncio
    async def test_cas_stage_conflict(self) -> None:
        """CAS update returns (False, row) → stage mismatch."""
        run = _make_run()
        run_service = _make_run_service(
            run=run, cas_result=(False, {"current_stage": "AUDIO_DONE"})
        )

        svc = TaskDispatchService()
        with pytest.raises(ConflictError, match="Stage conflict"):
            await svc.cas_dispatch_with_rollback(
                run_id=1,
                expected_stages=frozenset({"IDLE"}),
                target_stage="GENERATING",
                dispatcher=lambda **kw: "task-id",
                dispatcher_args={},
                run_service=run_service,
                rollback_stage="IDLE",
                rollback_restart_from=None,
                enqueue_error_detail="Enqueue failed",
            )


class TestCasDispatchRaisesQuotaExceeded:

    @pytest.mark.asyncio
    async def test_quota_exceeded(self) -> None:
        run = _make_run()
        run_service = _make_run_service(run=run)

        svc = TaskDispatchService()
        project_svc = SimpleNamespace(
            get_project=AsyncMock(return_value=_make_project()),
        )
        quota_mock = AsyncMock(return_value=(False, "Monthly limit reached"))

        with patch(
            "creator_service.project_service.project_service", project_svc
        ), patch(
            "creator_service.usage_service.check_workspace_quota", quota_mock
        ):
            with pytest.raises(QuotaExceededError, match="Monthly limit reached"):
                await svc.cas_dispatch_with_rollback(
                    run_id=1,
                    expected_stages=frozenset({"IDLE"}),
                    target_stage="GENERATING",
                    dispatcher=lambda **kw: "task-id",
                    dispatcher_args={},
                    run_service=run_service,
                    rollback_stage="IDLE",
                    rollback_restart_from=None,
                    enqueue_error_detail="Enqueue failed",
                    quota_operation_type="generate_script",
                    workspace_id=None,
                )


class TestCasDispatchRaisesServiceUnavailable:

    @pytest.mark.asyncio
    async def test_pre_check_failure_raises_unavailable(self) -> None:
        """When we can't even verify run status, raise ServiceUnavailableError."""
        async def failing_get_run(*args, **kwargs):
            raise RuntimeError("DB down")

        run_service = SimpleNamespace(
            get_run=failing_get_run,
            storage=AsyncMock(),
        )

        svc = TaskDispatchService()
        with pytest.raises(ServiceUnavailableError, match="Unable to verify"):
            await svc.cas_dispatch_with_rollback(
                run_id=1,
                expected_stages=frozenset({"IDLE"}),
                target_stage="GENERATING",
                dispatcher=lambda **kw: "task-id",
                dispatcher_args={},
                run_service=run_service,
                rollback_stage="IDLE",
                rollback_restart_from=None,
                enqueue_error_detail="Enqueue failed",
            )


class TestNoHttpExceptionImport:
    """task_dispatch_service must NOT import HTTPException."""

    def test_no_httpexception_import(self) -> None:
        import creator_service.task_dispatch_service as mod
        import inspect

        source = inspect.getsource(mod)
        assert "from fastapi import HTTPException" not in source
        assert "from fastapi import" not in source or "HTTPException" not in source


# -- Cleanup failure must not mask intended error ----------------------------


class TestCleanupFailureDoesNotMaskError:
    """When cleanup calls fail during rollback, the intended typed error still surfaces."""

    @pytest.mark.asyncio
    async def test_quota_cancel_failure_does_not_mask_enqueue_error(self) -> None:
        """cancel_workspace_quota_reservation failure must not prevent ServiceUnavailableError."""
        run = _make_run()
        project = _make_project(workspace_id=1)
        run_service = _make_run_service(run=run)

        svc = TaskDispatchService()
        svc._use_celery_dispatch = lambda: False

        def failing_dispatcher(**kw: Any) -> str:
            raise RuntimeError("broker down")

        async def _cancel_boom(*a: Any, **kw: Any) -> None:
            raise RuntimeError("quota cancel also failed")

        async def _check_quota_ok(*a: Any, **kw: Any) -> tuple[bool, str | None]:
            return (True, None)

        async def _get_project(*a: Any, **kw: Any) -> SimpleNamespace:
            return project

        mock_project_svc = SimpleNamespace(get_project=_get_project)

        with patch(
            "creator_service.project_service.project_service",
            mock_project_svc,
        ), patch(
            "creator_service.usage_service.cancel_workspace_quota_reservation",
            _cancel_boom,
        ), patch(
            "creator_service.usage_service.check_workspace_quota",
            _check_quota_ok,
        ):
            with pytest.raises(ServiceUnavailableError, match="Enqueue failed"):
                await svc.cas_dispatch_with_rollback(
                    run_id=1,
                    expected_stages=frozenset({"IDLE"}),
                    target_stage="GENERATING",
                    dispatcher=failing_dispatcher,
                    dispatcher_args={},
                    run_service=run_service,
                    rollback_stage="IDLE",
                    rollback_restart_from=None,
                    enqueue_error_detail="Enqueue failed",
                    workspace_id=1,
                    quota_operation_type="test_op",
                )


class TestInitialCasStorageFailure:
    """Storage/DB failure during the initial CAS update must surface as ServiceUnavailableError."""

    @pytest.mark.asyncio
    async def test_cas_storage_failure_raises_service_unavailable(self) -> None:
        """RuntimeError from conditional_update_run → ServiceUnavailableError, not raw exception."""
        run = _make_run()
        run_service = _make_run_service(run=run)
        # Make the CAS call raise a DB error
        run_service.storage.conditional_update_run = AsyncMock(
            side_effect=RuntimeError("db connection lost"),
        )

        svc = TaskDispatchService()
        with pytest.raises(ServiceUnavailableError, match="Storage failure"):
            await svc.cas_dispatch_with_rollback(
                run_id=1,
                expected_stages=frozenset({"IDLE"}),
                target_stage="GENERATING",
                dispatcher=lambda **kw: "task-id",
                dispatcher_args={},
                run_service=run_service,
                rollback_stage="IDLE",
                rollback_restart_from=None,
                enqueue_error_detail="Enqueue failed",
            )
