from __future__ import annotations

from dataclasses import dataclass

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
    request: _RequestStub = _RequestStub()


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
