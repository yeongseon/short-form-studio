import asyncio
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException

from creator_service.task_dispatch_service import (
    SynchronousTaskExecutionError,
    TaskDispatchService,
)


class _FakeRunStorage:
    def __init__(self) -> None:
        self.calls: list[
            tuple[int, dict[str, object], frozenset[str], int | None, frozenset[str] | None]
        ] = []

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        *,
        expected_stages: frozenset[str],
        workspace_id: int | None = None,
        rejected_statuses: frozenset[str] | None = None,
    ) -> tuple[bool, dict[str, object] | None]:
        self.calls.append((run_id, updates, expected_stages, workspace_id, rejected_statuses))
        return True, {"current_stage": "SCRIPT_REVIEW"}


class _FakeRunService:
    def __init__(self) -> None:
        self.storage = _FakeRunStorage()

    async def get_run(self, _run_id: int, **_kw: object) -> object:
        return SimpleNamespace(status="running", project_id=1)


def test_dispatch_generate_script_uses_sync_runner_when_redis_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    monkeypatch.delenv("REDIS_URL", raising=False)

    run_calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    class _FakeTask:
        def run(self, *args: object, **kwargs: object) -> dict[str, object]:
            run_calls.append((self, args, kwargs))
            return {"ok": True}

    def fake_import_module(name: str) -> object:
        if name == "tasks.generate_script":
            return SimpleNamespace(generate_script=_FakeTask())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    task_id = service.dispatch_generate_script(
        run_id=123,
        idea_brief="idea",
        model_key="qwen3-4b",
        instructions="extra",
    )

    assert task_id.startswith("sync-generate_script-123-")
    assert len(run_calls) == 1
    _, args, kwargs = run_calls[0]
    assert kwargs == {}
    assert len(args) == 5
    sync_self = args[0]
    assert getattr(getattr(sync_self, "request"), "id") == task_id
    assert args[1:] == (123, "idea", "qwen3-4b", "extra")


def test_dispatch_generate_script_uses_celery_when_redis_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    apply_async_calls: list[tuple[list[object], dict[str, object], dict[str, str]]] = []

    class _FakeTask:
        def apply_async(
            self,
            *,
            args: list[object],
            kwargs: dict[str, object],
            headers: dict[str, str],
        ) -> object:
            apply_async_calls.append((args, kwargs, headers))
            return SimpleNamespace(id="celery-789")

    def fake_import_module(name: str) -> object:
        if name == "tasks.generate_script":
            return SimpleNamespace(generate_script=_FakeTask())
        if name == "creator_service.telemetry":
            return SimpleNamespace(get_trace_headers=lambda: {"traceparent": "abc"})
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    task_id = service.dispatch_generate_script(
        run_id=11,
        idea_brief="idea",
        model_key="qwen3-4b",
        instructions=None,
    )

    assert task_id == "celery-789"
    assert apply_async_calls == [([11, "idea", "qwen3-4b", None], {}, {"traceparent": "abc"})]


def test_cas_dispatch_with_rollback_enqueue_failure_rolls_back_stage() -> None:
    service = TaskDispatchService()
    run_service = _FakeRunService()

    def failing_dispatcher(**_: object) -> str:
        raise RuntimeError("enqueue failed")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=42,
                expected_stages=frozenset({"SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=failing_dispatcher,
                dispatcher_args={"run_id": 42},
                run_service=run_service,
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="Failed to enqueue script generation task",
            )
        )

    assert exc.value.status_code == 503
    assert run_service.storage.calls[0][1] == {"current_stage": "SCRIPT_GENERATING"}
    assert run_service.storage.calls[1][1] == {
        "current_stage": "SCRIPT_REVIEW",
        "restart_from": None,
    }


def test_cas_dispatch_with_rollback_sync_execution_failure_does_not_rollback() -> None:
    service = TaskDispatchService()
    run_service = _FakeRunService()

    def failing_dispatcher(**_: object) -> str:
        raise SynchronousTaskExecutionError("task failed")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=99,
                expected_stages=frozenset({"SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=failing_dispatcher,
                dispatcher_args={"run_id": 99},
                run_service=run_service,
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="Failed to enqueue script generation task",
            )
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Task execution failed"
    assert len(run_service.storage.calls) == 1
    assert run_service.storage.calls[0][1] == {"current_stage": "SCRIPT_GENERATING"}


def test_cas_dispatch_with_rollback_record_failure_revokes_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    run_service = _FakeRunService()
    revoked: list[tuple[str, bool]] = []
    marked_revoked: list[str] = []

    def dispatch_generate_subtitles(**_: object) -> str:
        return "celery-123"

    class _TrackingService:
        async def record_task_queued(self, _run_id: int, _task_type: str, _task_id: str) -> None:
            raise RuntimeError("db write failed")

        async def mark_revoked(self, task_id: str) -> None:
            marked_revoked.append(task_id)

    celery_app_module = ModuleType("celery_app")
    setattr(
        celery_app_module,
        "celery_app",
        SimpleNamespace(
            control=SimpleNamespace(
                revoke=lambda task_id, terminate: revoked.append((task_id, terminate))
            )
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "celery_app", celery_app_module)

    def fake_import_module(name: str) -> object:
        if name == "creator_service.task_tracking_service":
            return SimpleNamespace(task_tracking_service=_TrackingService())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=7,
                expected_stages=frozenset({"AUDIO_GENERATING"}),
                target_stage="SUBTITLE_GENERATING",
                dispatcher=dispatch_generate_subtitles,
                dispatcher_args={"run_id": 7},
                run_service=run_service,
                rollback_stage="AUDIO_GENERATING",
                rollback_restart_from="AUDIO_GENERATING",
                enqueue_error_detail="Failed to enqueue subtitle generation task",
            )
        )

    assert exc.value.status_code == 503
    assert revoked == [("celery-123", True)]
    assert marked_revoked == ["celery-123"]
    assert run_service.storage.calls[1][1] == {
        "current_stage": "AUDIO_GENERATING",
        "restart_from": "AUDIO_GENERATING",
    }


def test_cas_dispatch_with_rollback_sync_dispatch_skips_record_task_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    run_service = _FakeRunService()
    queued_calls: list[tuple[int, str, str]] = []

    def dispatch_generate_script(**_: object) -> str:
        return "sync-generate_script-7-abc123"

    class _TrackingService:
        async def record_task_queued(self, run_id: int, task_type: str, task_id: str) -> None:
            queued_calls.append((run_id, task_type, task_id))

    def fake_import_module(name: str) -> object:
        if name == "creator_service.task_tracking_service":
            return SimpleNamespace(task_tracking_service=_TrackingService())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    result = asyncio.run(
        service.cas_dispatch_with_rollback(
            run_id=7,
            expected_stages=frozenset({"SCRIPT_REVIEW"}),
            target_stage="SCRIPT_GENERATING",
            dispatcher=dispatch_generate_script,
            dispatcher_args={"run_id": 7},
            run_service=run_service,
            rollback_stage="SCRIPT_REVIEW",
            rollback_restart_from=None,
            enqueue_error_detail="Failed to enqueue script generation task",
        )
    )

    assert result["task_id"] == "sync-generate_script-7-abc123"
    assert queued_calls == []


def test_cas_dispatch_with_rollback_celery_dispatch_records_task_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    run_service = _FakeRunService()
    queued_calls: list[tuple[int, str, str]] = []

    def dispatch_generate_script(**_: object) -> str:
        return "celery-123"

    class _TrackingService:
        async def record_task_queued(self, run_id: int, task_type: str, task_id: str) -> None:
            queued_calls.append((run_id, task_type, task_id))

    def fake_import_module(name: str) -> object:
        if name == "creator_service.task_tracking_service":
            return SimpleNamespace(task_tracking_service=_TrackingService())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    result = asyncio.run(
        service.cas_dispatch_with_rollback(
            run_id=7,
            expected_stages=frozenset({"SCRIPT_REVIEW"}),
            target_stage="SCRIPT_GENERATING",
            dispatcher=dispatch_generate_script,
            dispatcher_args={"run_id": 7},
            run_service=run_service,
            rollback_stage="SCRIPT_REVIEW",
            rollback_restart_from=None,
            enqueue_error_detail="Failed to enqueue script generation task",
        )
    )

    assert result["task_id"] == "celery-123"
    assert queued_calls == [(7, "generate_script", "celery-123")]


def test_cas_dispatch_with_rollback_releases_quota_on_stage_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    cancel_calls: list[tuple[int, str]] = []

    class _ConflictRunStorage:
        async def conditional_update_run(
            self,
            _run_id: int,
            _updates: dict[str, object],
            *,
            expected_stages: frozenset[str],
            workspace_id: int | None = None,
            rejected_statuses: frozenset[str] | None = None,
        ) -> tuple[bool, dict[str, object] | None]:
            _ = expected_stages
            _ = workspace_id
            _ = rejected_statuses
            return False, {"current_stage": "SCRIPT_GENERATING"}

    class _ConflictRunService:
        def __init__(self) -> None:
            self.storage = _ConflictRunStorage()

        async def get_run(self, _run_id: int) -> object:
            return SimpleNamespace(project_id=55)

    class _ProjectService:
        async def get_project(self, _project_id: int) -> object:
            return SimpleNamespace(workspace_id=999)

    async def _check_workspace_quota(
        _workspace_id: int, operation_type: str = "llm"
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    async def _cancel_workspace_quota_reservation(workspace_id: int, operation_type: str) -> None:
        cancel_calls.append((workspace_id, operation_type))

    def _fake_dispatcher(**_: object) -> str:
        return "celery-never-called"

    import sys
    import types

    project_service_module = types.ModuleType("creator_service.project_service")
    setattr(project_service_module, "project_service", _ProjectService())
    usage_service_module = types.ModuleType("creator_service.usage_service")
    setattr(usage_service_module, "check_workspace_quota", _check_workspace_quota)
    setattr(
        usage_service_module,
        "cancel_workspace_quota_reservation",
        _cancel_workspace_quota_reservation,
    )

    monkeypatch.setitem(sys.modules, "creator_service.project_service", project_service_module)
    monkeypatch.setitem(sys.modules, "creator_service.usage_service", usage_service_module)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=123,
                expected_stages=frozenset({"SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=_fake_dispatcher,
                dispatcher_args={"run_id": 123},
                run_service=_ConflictRunService(),
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="enqueue failed",
                quota_operation_type="llm",
            )
        )

    assert exc.value.status_code == 409
    assert cancel_calls == [(999, "llm")]


def test_cas_dispatch_with_rollback_rejects_cancelled_run() -> None:
    """cas_dispatch_with_rollback must refuse to dispatch for cancelled runs."""
    service = TaskDispatchService()

    class _CancelledRunStorage:
        async def conditional_update_run(
            self,
            _run_id: int,
            _updates: dict[str, object],
            *,
            expected_stages: frozenset[str],
            workspace_id: int | None = None,
            rejected_statuses: frozenset[str] | None = None,
        ) -> tuple[bool, dict[str, object] | None]:
            _ = expected_stages
            _ = workspace_id
            _ = rejected_statuses
            raise AssertionError("Should not reach CAS update for cancelled run")

    class _CancelledRunService:
        def __init__(self) -> None:
            self.storage = _CancelledRunStorage()

        async def get_run(self, _run_id: int, **_kw: object) -> object:
            return SimpleNamespace(status="cancelled", project_id=1)

    def _dispatcher(**_: object) -> str:
        raise AssertionError("Should not dispatch for cancelled run")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=42,
                expected_stages=frozenset({"IDEA_READY", "SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=_dispatcher,
                dispatcher_args={"run_id": 42},
                run_service=_CancelledRunService(),
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="Failed to enqueue",
            )
        )

    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail.lower()


def test_cas_dispatch_rejects_concurrent_cancellation_atomically() -> None:
    service = TaskDispatchService()

    class _ConcurrentCancelStorage:
        async def conditional_update_run(
            self,
            _run_id: int,
            _updates: dict[str, object],
            *,
            expected_stages: frozenset[str],
            workspace_id: int | None = None,
            rejected_statuses: frozenset[str] | None = None,
        ) -> tuple[bool, dict[str, object] | None]:
            _ = expected_stages
            _ = workspace_id
            _ = rejected_statuses
            return False, {"current_stage": "SCRIPT_GENERATING", "status": "cancelled"}

    class _ConcurrentCancelRunService:
        def __init__(self) -> None:
            self.storage = _ConcurrentCancelStorage()

        async def get_run(self, _run_id: int, **_kw: object) -> object:
            return SimpleNamespace(status="running", project_id=1)

    def _dispatcher(**_: object) -> str:
        raise AssertionError("Should not dispatch when CAS rejects cancelled run")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=42,
                expected_stages=frozenset({"SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=_dispatcher,
                dispatcher_args={"run_id": 42},
                run_service=_ConcurrentCancelRunService(),
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="Failed to enqueue",
            )
        )

    assert exc.value.status_code == 409


def test_cas_dispatch_with_rollback_allows_non_cancelled_run() -> None:
    """cas_dispatch_with_rollback proceeds normally for non-cancelled runs."""
    service = TaskDispatchService()
    run_service = _FakeRunService()

    # Patch get_run onto _FakeRunService so the cancelled-check can fetch status
    async def _get_run(_run_id: int, **_kw: object) -> object:
        return SimpleNamespace(status="running", project_id=1)

    run_service.get_run = _get_run  # type: ignore[attr-defined]

    def _dispatcher(**_: object) -> str:
        return "sync-test-1-abc"

    result = asyncio.run(
        service.cas_dispatch_with_rollback(
            run_id=7,
            expected_stages=frozenset({"SCRIPT_REVIEW"}),
            target_stage="SCRIPT_GENERATING",
            dispatcher=_dispatcher,
            dispatcher_args={"run_id": 7},
            run_service=run_service,
            rollback_stage="SCRIPT_REVIEW",
            rollback_restart_from=None,
            enqueue_error_detail="Failed to enqueue",
        )
    )

    assert result["task_id"] == "sync-test-1-abc"


def test_cas_dispatch_post_dispatch_revoke_on_concurrent_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    revoked: list[tuple[str, bool]] = []

    class _Storage:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def conditional_update_run(
            self,
            run_id: int,
            updates: dict[str, object],
            *,
            expected_stages: frozenset[str],
            workspace_id: int | None = None,
            rejected_statuses: frozenset[str] | None = None,
        ) -> tuple[bool, dict[str, object] | None]:
            self.calls.append(
                {
                    "run_id": run_id,
                    "updates": updates,
                    "expected_stages": expected_stages,
                    "workspace_id": workspace_id,
                    "rejected_statuses": rejected_statuses,
                }
            )
            return True, {"current_stage": "SCRIPT_GENERATING"}

    class _RunService:
        def __init__(self) -> None:
            self.storage = _Storage()
            self._calls = 0

        async def get_run(self, _run_id: int, **_kw: object) -> object:
            self._calls += 1
            if self._calls == 1:
                return SimpleNamespace(status="running", project_id=1)
            return SimpleNamespace(status="cancelled", project_id=1)

    class _TrackingService:
        async def record_task_queued(self, _run_id: int, _task_type: str, _task_id: str) -> None:
            return None

        async def mark_tasks_revoked(self, _task_ids: list[str]) -> None:
            return None

    celery_app_module = ModuleType("celery_app")
    setattr(
        celery_app_module,
        "celery_app",
        SimpleNamespace(
            control=SimpleNamespace(
                revoke=lambda task_id, terminate: revoked.append((task_id, terminate))
            )
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "celery_app", celery_app_module)

    def fake_import_module(name: str) -> object:
        if name == "creator_service.task_tracking_service":
            return SimpleNamespace(task_tracking_service=_TrackingService())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    run_service = _RunService()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=42,
                expected_stages=frozenset({"SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=lambda **_: "celery-999",
                dispatcher_args={"run_id": 42},
                run_service=run_service,
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="Failed to enqueue",
            )
        )

    assert exc.value.status_code == 409
    assert revoked == [("celery-999", True)]
    assert run_service.storage.calls[1]["updates"] == {
        "current_stage": "SCRIPT_REVIEW",
        "restart_from": None,
    }


def test_cas_dispatch_with_rollback_returns_503_when_get_run_raises() -> None:
    """Fail-closed: if get_run raises, dispatch must be blocked with 503."""
    service = TaskDispatchService()

    class _ErrorRunStorage:
        async def conditional_update_run(self, *_a: object, **_kw: object) -> object:
            raise AssertionError("Should not reach CAS update")

    class _ErrorRunService:
        def __init__(self) -> None:
            self.storage = _ErrorRunStorage()

        async def get_run(self, _run_id: int, **_kw: object) -> object:
            raise RuntimeError("DB connection lost")

    def _dispatcher(**_: object) -> str:
        raise AssertionError("Should not dispatch")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=42,
                expected_stages=frozenset({"SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=_dispatcher,
                dispatcher_args={"run_id": 42},
                run_service=_ErrorRunService(),
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="Failed to enqueue",
            )
        )

    assert exc.value.status_code == 503
    assert "verify run status" in exc.value.detail.lower()


def test_cas_dispatch_with_rollback_returns_404_when_get_run_returns_none() -> None:
    """If get_run returns None, dispatch must be blocked with 404."""
    service = TaskDispatchService()

    class _NoneRunStorage:
        async def conditional_update_run(self, *_a: object, **_kw: object) -> object:
            raise AssertionError("Should not reach CAS update")

    class _NoneRunService:
        def __init__(self) -> None:
            self.storage = _NoneRunStorage()

        async def get_run(self, _run_id: int, **_kw: object) -> object:
            return None

    def _dispatcher(**_: object) -> str:
        raise AssertionError("Should not dispatch")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.cas_dispatch_with_rollback(
                run_id=999,
                expected_stages=frozenset({"SCRIPT_REVIEW"}),
                target_stage="SCRIPT_GENERATING",
                dispatcher=_dispatcher,
                dispatcher_args={"run_id": 999},
                run_service=_NoneRunService(),
                rollback_stage="SCRIPT_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="Failed to enqueue",
            )
        )

    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail.lower()


def test_cas_dispatch_with_rollback_passes_workspace_id_to_preflight() -> None:
    """Preflight get_run must forward workspace_id to match run_service contract."""
    service = TaskDispatchService()
    received_kwargs: list[dict[str, object]] = []

    class _StrictRunStorage:
        async def conditional_update_run(
            self,
            _run_id: int,
            _updates: dict[str, object],
            *,
            expected_stages: frozenset[str],
            workspace_id: int | None = None,
            rejected_statuses: frozenset[str] | None = None,
        ) -> tuple[bool, dict[str, object] | None]:
            _ = expected_stages
            _ = workspace_id
            _ = rejected_statuses
            return True, {"current_stage": "SCRIPT_GENERATING", "id": 42}

    class _StrictRunService:
        def __init__(self) -> None:
            self.storage = _StrictRunStorage()

        async def get_run(self, run_id: int, *, workspace_id: int | None = None) -> object:
            received_kwargs.append({"run_id": run_id, "workspace_id": workspace_id})
            return SimpleNamespace(status="running", project_id=1)

    dispatched = False

    def _dispatcher(**_: object) -> str:
        nonlocal dispatched
        dispatched = True
        return "sync-test-42"

    asyncio.run(
        service.cas_dispatch_with_rollback(
            run_id=42,
            expected_stages=frozenset({"IDEA_READY", "SCRIPT_REVIEW"}),
            target_stage="SCRIPT_GENERATING",
            dispatcher=_dispatcher,
            dispatcher_args={"run_id": 42},
            run_service=_StrictRunService(),
            rollback_stage="SCRIPT_REVIEW",
            rollback_restart_from=None,
            enqueue_error_detail="Failed to enqueue",
            workspace_id=7,
        )
    )

    assert dispatched
    # The preflight call MUST have received workspace_id=7
    assert len(received_kwargs) >= 1
    assert received_kwargs[0]["workspace_id"] == 7
