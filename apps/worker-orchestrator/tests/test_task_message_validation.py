from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from tasks import task_runner
from tasks.task_runner import TaskRunnerConfig, run_task, validate_task_message


def test_validate_task_message_accepts_valid_payload() -> None:
    payload = {
        "run_id": 123,
        "task_name": "generate_script",
        "args": ["topic"],
        "kwargs": {"language": "en"},
    }
    assert validate_task_message(payload)["run_id"] == 123


@pytest.mark.parametrize(
    "payload, error_match",
    [
        ({}, "missing required field: run_id"),
        ({"run_id": "123"}, "run_id must be int"),
        ({"run_id": 0}, "run_id must be positive"),
        ({"run_id": -5}, "run_id must be positive"),
        ({"run_id": True}, "run_id must be int"),
        ({"run_id": 1, "task_name": 2}, "task_name must be str"),
        ({"run_id": 1, "args": "bad"}, "args must be list"),
        ({"run_id": 1, "kwargs": []}, "kwargs must be dict"),
    ],
)
def test_validate_task_message_rejects_malformed_payload(payload, error_match: str) -> None:
    with pytest.raises(ValueError, match=error_match):
        validate_task_message(payload)


@dataclass
class _RequestStub:
    id: str = "task-1"


@dataclass
class _CelerySelfStub:
    request: object = _RequestStub()


async def _never_execute(_ctx: Any) -> Any:
    raise AssertionError("execute must not run")


def test_run_task_rejects_malformed_payload_at_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"inner": False}

    async def _never_called(_ctx):
        raise AssertionError("execute must not run")

    def _track_asyncio_run(_coroutine):
        called["inner"] = True
        raise AssertionError("_run_task_inner must not run for malformed payload")

    monkeypatch.setattr("tasks.task_runner.asyncio.run", _track_asyncio_run)

    config = TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({task_runner.RunStage.IDEA_READY}),
        safe_stages=frozenset({task_runner.RunStage.IDEA_READY.value}),
    )
    with pytest.raises(ValueError, match="run_id must be int"):
        run_task(_CelerySelfStub(), "not-an-int", config, _never_called)  # type: ignore[arg-type]
    assert called["inner"] is False


@dataclass
class _RequestStubWithArgs:
    id: str = "task-1"
    args: object = ()
    kwargs: object = None


def test_run_task_rejects_string_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """args that are a string should be rejected, not coerced to list of chars."""

    def _track_asyncio_run(_coroutine):
        raise AssertionError("_run_task_inner must not run")

    monkeypatch.setattr("tasks.task_runner.asyncio.run", _track_asyncio_run)

    stub = _CelerySelfStub(request=_RequestStubWithArgs(args="evil", kwargs={}))
    config = TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({task_runner.RunStage.IDEA_READY}),
        safe_stages=frozenset({task_runner.RunStage.IDEA_READY.value}),
    )
    with pytest.raises(ValueError, match="args is str"):
        run_task(stub, 1, config, _never_execute)


def test_run_task_rejects_list_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    """kwargs that are a list should be rejected, not coerced to dict."""

    def _track_asyncio_run(_coroutine):
        raise AssertionError("_run_task_inner must not run")

    monkeypatch.setattr("tasks.task_runner.asyncio.run", _track_asyncio_run)

    stub = _CelerySelfStub(request=_RequestStubWithArgs(args=(), kwargs=[("a", "b")]))
    config = TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({task_runner.RunStage.IDEA_READY}),
        safe_stages=frozenset({task_runner.RunStage.IDEA_READY.value}),
    )
    with pytest.raises(ValueError, match="kwargs is list"):
        run_task(stub, 1, config, _never_execute)


def test_run_task_rejects_falsy_empty_string_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty string args (falsy) should be rejected, not coerced via 'or ()'."""

    def _track_asyncio_run(_coroutine):
        raise AssertionError("_run_task_inner must not run")

    monkeypatch.setattr("tasks.task_runner.asyncio.run", _track_asyncio_run)

    stub = _CelerySelfStub(request=_RequestStubWithArgs(args="", kwargs={}))
    config = TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({task_runner.RunStage.IDEA_READY}),
        safe_stages=frozenset({task_runner.RunStage.IDEA_READY.value}),
    )
    with pytest.raises(ValueError, match="args is str"):
        run_task(stub, 1, config, _never_execute)


def test_run_task_rejects_during_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """During graceful shutdown, tasks should be rejected via Ignore without failure handling."""
    import celery_app as celery_module
    from celery.exceptions import Ignore

    celery_module._SHUTDOWN_REQUESTED = True

    failure_called = {"count": 0}

    original_asyncio_run = task_runner.asyncio.run

    def _tracking_asyncio_run(coro):
        # _run_task_inner should raise Ignore immediately
        return original_asyncio_run(coro)

    monkeypatch.setattr("tasks.task_runner.asyncio.run", _tracking_asyncio_run)
    monkeypatch.setattr(
        "tasks.task_runner._handle_general_failure",
        lambda *a, **kw: failure_called.update(count=failure_called["count"] + 1),
    )

    config = TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({task_runner.RunStage.IDEA_READY}),
        safe_stages=frozenset({task_runner.RunStage.IDEA_READY.value}),
    )

    with pytest.raises(Ignore):
        run_task(_CelerySelfStub(), 1, config, _never_execute)

    assert failure_called["count"] == 0, (
        "_handle_general_failure must not be called during shutdown"
    )
    celery_module._SHUTDOWN_REQUESTED = False


def test_run_task_value_error_marks_task_failed_without_run_failed_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TrackingServiceStub:
        def __init__(self) -> None:
            self.failed_calls: list[tuple[str, str, str]] = []

        async def record_task_start(self, run_id: int, task_name: str, task_id: str) -> None:
            return None

        async def mark_running(self, task_id: str) -> None:
            return None

        async def mark_failed(self, task_id: str, error_code: str, error_message: str) -> None:
            self.failed_calls.append((task_id, error_code, error_message))

    class _StorageStub:
        def __init__(self) -> None:
            self.failed_transition_calls = 0

        async def get_run(self, run_id: int) -> dict[str, object] | None:
            return {"id": run_id, "current_stage": task_runner.RunStage.IDEA_READY.value}

        async def conditional_update_run(self, *args, **kwargs):
            self.failed_transition_calls += 1
            return True, None

    async def _raise_value_error(_ctx):
        raise ValueError("bad payload")

    tracking = _TrackingServiceStub()
    storage = _StorageStub()
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)
    monkeypatch.setattr(task_runner, "_run_service", SimpleNamespace(storage=storage))

    config = TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({task_runner.RunStage.IDEA_READY}),
        safe_stages=frozenset({task_runner.RunStage.IDEA_READY.value}),
        no_fail_transition_exceptions=(ValueError,),
    )

    with pytest.raises(ValueError, match="bad payload"):
        run_task(_CelerySelfStub(), 1, config, _raise_value_error)

    assert tracking.failed_calls == [("task-1", "ValueError", "bad payload")]
    assert storage.failed_transition_calls == 0
