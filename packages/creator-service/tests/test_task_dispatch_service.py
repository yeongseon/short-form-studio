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
        self.calls: list[tuple[int, dict[str, object], frozenset[str]]] = []

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        *,
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, object] | None]:
        self.calls.append((run_id, updates, expected_stages))
        return True, {"current_stage": "SCRIPT_REVIEW"}


class _FakeRunService:
    def __init__(self) -> None:
        self.storage = _FakeRunStorage()


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
