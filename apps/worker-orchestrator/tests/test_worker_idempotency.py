from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from tasks import generate_script as generate_script_module
from tasks import task_runner


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class _TrackingStorageStub:
    def __init__(self, existing: dict[str, Any] | None = None) -> None:
        self.existing = existing

    async def get_by_celery_id(self, task_id: str) -> dict[str, Any] | None:
        if self.existing is None:
            return None
        if self.existing.get("celery_task_id") == task_id:
            return dict(self.existing)
        return None


class _TrackingServiceStub:
    def __init__(self, existing: dict[str, Any] | None = None) -> None:
        self.storage = _TrackingStorageStub(existing)
        self.started = 0

    async def record_task_start(self, run_id: int, task_name: str, task_id: str) -> SimpleNamespace:
        self.started += 1
        return SimpleNamespace(status="running")

    async def mark_success(self, task_id: str) -> None:
        return None

    async def mark_failed(self, task_id: str, error_code: str, error_message: str) -> None:
        return None


class _RunStorageStub:
    def __init__(self, stage: str = task_runner.RunStage.IDEA_READY.value) -> None:
        self.stage = stage

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        return {"id": run_id, "current_stage": self.stage, "project_id": 1}

    async def conditional_update_run(
        self, *args: Any, **kwargs: Any
    ) -> tuple[bool, dict[str, Any] | None]:
        return True, None


def _config() -> task_runner.TaskRunnerConfig:
    return task_runner.TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({task_runner.RunStage.IDEA_READY}),
        safe_stages=frozenset({task_runner.RunStage.IDEA_READY.value}),
        success_stage=task_runner.RunStage.SCRIPT_REVIEW.value,
    )


def test_task_runner_skips_already_succeeded_task(monkeypatch) -> None:
    tracking = _TrackingServiceStub(
        existing={
            "celery_task_id": "task-1",
            "status": "success",
            "run_id": 1,
            "task_type": "generate_script",
        }
    )
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))
    monkeypatch.setattr(task_runner, "resolve_workspace_id_from_run", lambda _run_id: None)

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    result = run(task_runner._run_task_inner(1, "task-1", _config(), _execute))

    assert calls["execute"] == 0
    assert result["status"] == "success"
    assert result["idempotent_skip"] is True
    assert tracking.started == 0


def test_task_runner_executes_when_no_prior_success(monkeypatch) -> None:
    tracking = _TrackingServiceStub(existing=None)
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))

    async def _resolve_workspace_id_from_run(_run_id: int) -> int:
        return 1

    monkeypatch.setattr(
        task_runner, "resolve_workspace_id_from_run", _resolve_workspace_id_from_run
    )

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    result = run(task_runner._run_task_inner(1, "task-2", _config(), _execute))

    assert calls["execute"] == 1
    assert result.get("idempotent_skip") is None
    assert tracking.started == 1


def test_task_runner_does_not_skip_when_task_type_differs(monkeypatch) -> None:
    tracking = _TrackingServiceStub(
        existing={
            "celery_task_id": "task-2b",
            "status": "success",
            "run_id": 1,
            "task_type": "generate_audio",
        }
    )
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))

    async def _resolve_workspace_id_from_run(_run_id: int) -> int:
        return 1

    monkeypatch.setattr(
        task_runner, "resolve_workspace_id_from_run", _resolve_workspace_id_from_run
    )

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    run(task_runner._run_task_inner(1, "task-2b", _config(), _execute))

    assert calls["execute"] == 1


def test_task_runner_executes_when_prior_task_failed(monkeypatch) -> None:
    tracking = _TrackingServiceStub(existing={"celery_task_id": "task-3", "status": "failed"})
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))

    async def _resolve_workspace_id_from_run(_run_id: int) -> int:
        return 1

    monkeypatch.setattr(
        task_runner, "resolve_workspace_id_from_run", _resolve_workspace_id_from_run
    )

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    run(task_runner._run_task_inner(1, "task-3", _config(), _execute))
    assert calls["execute"] == 1


def test_task_runner_executes_when_prior_task_running(monkeypatch) -> None:
    tracking = _TrackingServiceStub(existing={"celery_task_id": "task-4", "status": "running"})
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))

    async def _resolve_workspace_id_from_run(_run_id: int) -> int:
        return 1

    monkeypatch.setattr(
        task_runner, "resolve_workspace_id_from_run", _resolve_workspace_id_from_run
    )

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    run(task_runner._run_task_inner(1, "task-4", _config(), _execute))
    assert calls["execute"] == 1


def test_generate_script_passes_idempotency_key(monkeypatch) -> None:
    class _FakeProvider:
        async def generate(self, prompt: str, params: dict[str, object] | None = None) -> str:
            return "generated"

    class _FakeEntry:
        provider_type = "ollama"
        endpoint = "http://fake"
        requires_gpu = False
        default_params: dict[str, object] | None = None

    class _FakeRegistry:
        def resolve(self, model_key: str) -> _FakeEntry:
            return _FakeEntry()

        def get_provider(self, model_key: str) -> _FakeProvider:
            return _FakeProvider()

    class _ProviderRegistry:
        @staticmethod
        def create_default() -> _FakeRegistry:
            return _FakeRegistry()

    class _ScriptService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def save_draft(
            self,
            run_id: int,
            source_type: str,
            markdown_content: str | None = None,
            *,
            idempotency_key: str | None = None,
        ) -> dict[str, Any]:
            self.calls.append(
                {
                    "run_id": run_id,
                    "source_type": source_type,
                    "markdown_content": markdown_content,
                    "idempotency_key": idempotency_key,
                }
            )
            return {"id": 1}

    class _Storage:
        async def get_run(self, run_id: int) -> dict[str, Any] | None:
            return {
                "id": run_id,
                "current_stage": task_runner.RunStage.IDEA_READY.value,
                "project_id": 1,
            }

        async def conditional_update_run(
            self, *args: Any, **kwargs: Any
        ) -> tuple[bool, dict[str, Any] | None]:
            return True, None

    class _Tracking:
        class _TrackingStorage:
            async def get_by_celery_id(self, task_id: str) -> dict[str, Any] | None:
                return None

        storage = _TrackingStorage()

        async def record_task_start(
            self, run_id: int, task_name: str, task_id: str
        ) -> SimpleNamespace:
            return SimpleNamespace(status="running")

        async def mark_success(self, task_id: str) -> None:
            return None

        async def mark_failed(self, task_id: str, error_code: str, error_message: str) -> None:
            return None

    script_service = _ScriptService()
    monkeypatch.setattr(generate_script_module, "ProviderRegistry", _ProviderRegistry)
    monkeypatch.setattr(generate_script_module, "_script_service", script_service)
    monkeypatch.setattr(
        generate_script_module, "record_provider_call", lambda *args, **kwargs: asyncio.sleep(0)
    )
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_Storage()))
    monkeypatch.setattr(task_runner, "_task_tracking_service", _Tracking())

    async def _resolve_workspace_id(_run_id: int) -> int:
        return 1

    monkeypatch.setattr(task_runner, "resolve_workspace_id_from_run", _resolve_workspace_id)

    task = generate_script_module.generate_script
    run_callable: Any = getattr(task, "run", task)
    run_callable(run_id=123, idea_brief="idea", model_key="qwen3-4b")

    assert script_service.calls
    assert script_service.calls[0]["idempotency_key"] == "run-123"


# --- Race condition tests ---


class _TrackingServiceRaceStub:
    """Simulates a race: task becomes success between guard read and record_task_start."""

    def __init__(self) -> None:
        self._call_count = 0
        self.storage = _TrackingStorageStubRace()
        self.started = 0

    async def record_task_start(self, run_id: int, task_name: str, task_id: str) -> SimpleNamespace:
        self.started += 1
        # Return status="success" to simulate concurrent completion
        return SimpleNamespace(status="success")

    async def mark_success(self, task_id: str) -> None:
        return None

    async def mark_failed(self, task_id: str, error_code: str, error_message: str) -> None:
        return None


class _TrackingStorageStubRace:
    """Guard lookup returns running (not success), but record_task_start returns success."""

    async def get_by_celery_id(self, task_id: str) -> dict[str, Any] | None:
        return {
            "celery_task_id": task_id,
            "status": "running",
            "run_id": 1,
            "task_type": "generate_script",
        }


def test_task_runner_skips_when_task_succeeds_between_guard_and_start(monkeypatch) -> None:
    """TOCTOU race: guard sees 'running', but record_task_start returns 'success'."""
    tracking = _TrackingServiceRaceStub()
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))
    monkeypatch.setattr(task_runner, "resolve_workspace_id_from_run", lambda _run_id: None)

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    result = run(task_runner._run_task_inner(1, "task-race-1", _config(), _execute))

    assert calls["execute"] == 0, "Should NOT execute when record_task_start returns success"
    assert result["status"] == "success"
    assert result["idempotent_skip"] is True
    assert tracking.started == 1


def test_inmemory_update_task_status_refuses_overwrite_success() -> None:
    """InMemory storage must not overwrite success status."""
    from creator_service.task_tracking_service import InMemoryTaskTrackingStorage

    storage = InMemoryTaskTrackingStorage()

    async def _test() -> None:
        row = await storage.create_task(
            {"run_id": 1, "task_type": "gen", "celery_task_id": "t1", "status": "running"}
        )
        # Mark success
        await storage.update_task_status(row["id"], "success")
        # Attempt to overwrite with running
        result = await storage.update_task_status(row["id"], "running")
        assert result is None, "Should refuse to overwrite success"
        # Verify still success
        fetched = await storage.get_by_celery_id("t1")
        assert fetched is not None
        assert fetched["status"] == "success"

    run(_test())


def test_record_task_start_returns_success_when_concurrent_completion() -> None:
    """record_task_start returns success RunTask when update_task_status returns None."""
    from creator_service.task_tracking_service import (
        TaskTrackingService,
        InMemoryTaskTrackingStorage,
    )

    storage = InMemoryTaskTrackingStorage()
    service = TaskTrackingService(storage)

    async def _test() -> None:
        # Create and mark success
        await storage.create_task(
            {"run_id": 1, "task_type": "gen", "celery_task_id": "t2", "status": "running"}
        )
        task = await storage.get_by_celery_id("t2")
        assert task is not None
        await storage.update_task_status(task["id"], "success")

        # Now record_task_start should return the success row
        result = await service.record_task_start(1, "gen", "t2")
        assert result.status == "success"

    run(_test())


def test_task_runner_skips_when_claim_fails(monkeypatch) -> None:
    """task_runner must skip execution when record_task_start returns None (already claimed)."""

    class _ClaimFailedTracking:
        class _Storage:
            async def get_by_celery_id(self, task_id: str) -> dict[str, Any] | None:
                return {
                    "celery_task_id": task_id,
                    "status": "running",
                    "run_id": 1,
                    "task_type": "generate_script",
                }

        storage = _Storage()

        async def record_task_start(self, run_id: int, task_name: str, task_id: str) -> None:
            return None  # Claim failed

        async def mark_success(self, task_id: str) -> None:
            return None

        async def mark_failed(self, task_id: str, error_code: str, error_message: str) -> None:
            return None

    monkeypatch.setattr(task_runner, "_task_tracking_service", _ClaimFailedTracking())
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))
    monkeypatch.setattr(task_runner, "resolve_workspace_id_from_run", lambda _run_id: None)

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    result = run(task_runner._run_task_inner(1, "task-claim-fail", _config(), _execute))

    assert calls["execute"] == 0, "Must NOT execute when claim fails"
    assert result["status"] == "success"
    assert result["idempotent_skip"] is True


def test_task_runner_raises_when_claim_errors(monkeypatch) -> None:
    """task_runner must NOT execute when record_task_start raises (fail-closed)."""

    class _ClaimErrorTracking:
        class _Storage:
            async def get_by_celery_id(self, task_id: str) -> dict[str, Any] | None:
                return None

        storage = _Storage()

        async def record_task_start(self, run_id: int, task_name: str, task_id: str) -> None:
            raise RuntimeError("DB connection lost")

        async def mark_success(self, task_id: str) -> None:
            return None

        async def mark_failed(self, task_id: str, error_code: str, error_message: str) -> None:
            return None

    monkeypatch.setattr(task_runner, "_task_tracking_service", _ClaimErrorTracking())
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=_RunStorageStub()))
    monkeypatch.setattr(task_runner, "resolve_workspace_id_from_run", lambda _run_id: None)

    calls = {"execute": 0}

    async def _execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        calls["execute"] += 1
        return task_runner.TaskResult(status="success")

    import pytest

    with pytest.raises(RuntimeError, match="DB connection lost"):
        run(task_runner._run_task_inner(1, "task-err-1", _config(), _execute))

    assert calls["execute"] == 0, "Must NOT execute when claim raises"
