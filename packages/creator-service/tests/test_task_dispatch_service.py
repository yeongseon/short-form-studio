import asyncio
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException

from creator_service.task_dispatch_service import TaskDispatchService


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
