import asyncio
from types import SimpleNamespace

import pytest

from creator_service.task_dispatch_service import SynchronousTaskExecutionError, TaskDispatchService


def test_lightweight_dispatch_runs_in_thread_without_event_loop_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    monkeypatch.delenv("REDIS_URL", raising=False)

    run_thread_names: list[str] = []

    class _FakeTask:
        def run(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            import threading

            run_thread_names.append(threading.current_thread().name)
            asyncio.run(asyncio.sleep(0))
            return {"ok": True}

    def fake_import_module(name: str) -> object:
        if name == "tasks.generate_script":
            return SimpleNamespace(generate_script=_FakeTask())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    async def _invoke() -> str:
        return service.dispatch_generate_script(1, "idea", "model", None)

    task_id = asyncio.run(_invoke())

    assert task_id.startswith("sync-generate_script-1-")
    assert len(run_thread_names) == 1
    assert "ThreadPoolExecutor" in run_thread_names[0]


def test_lightweight_dispatch_wraps_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaskDispatchService()
    monkeypatch.delenv("REDIS_URL", raising=False)

    mark_failed_calls: list[int] = []

    class _FakeTask:
        def run(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("boom")

    def fake_import_module(name: str) -> object:
        if name == "tasks.generate_script":
            return SimpleNamespace(generate_script=_FakeTask())
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)
    monkeypatch.setattr(
        service, "_mark_run_failed", lambda run_id: mark_failed_calls.append(run_id)
    )

    with pytest.raises(SynchronousTaskExecutionError):
        service.dispatch_generate_script(22, "idea", "model", None)

    assert mark_failed_calls == [22]


def test_dispatch_uses_celery_path_when_redis_set(monkeypatch: pytest.MonkeyPatch) -> None:
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
            return SimpleNamespace(id="celery-456")

    def fake_import_module(name: str) -> object:
        if name == "tasks.generate_script":
            return SimpleNamespace(generate_script=_FakeTask())
        if name == "creator_service.telemetry":
            return SimpleNamespace(get_trace_headers=lambda: {"traceparent": "trace"})
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("creator_service.task_dispatch_service.import_module", fake_import_module)

    task_id = service.dispatch_generate_script(9, "idea", "model", "instructions")

    assert task_id == "celery-456"
    assert apply_async_calls == [
        ([9, "idea", "model", "instructions"], {}, {"traceparent": "trace"})
    ]
