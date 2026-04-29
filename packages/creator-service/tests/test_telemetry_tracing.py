from contextlib import contextmanager

import creator_service.telemetry as telemetry


class _SpyTracer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    @contextmanager
    def start_as_current_span(self, name: str, attributes=None):
        self.calls.append((name, attributes))
        yield


def test_trace_task_wraps_execution_in_span(monkeypatch):
    tracer = _SpyTracer()
    monkeypatch.setattr(telemetry, "get_tracer", lambda *_args, **_kwargs: tracer)

    called = {"value": False}

    @telemetry.trace_task("generate_audio")
    def _task(run_id: int) -> int:
        called["value"] = True
        return run_id + 1

    result = _task(41)

    assert called["value"] is True
    assert result == 42
    assert tracer.calls == [
        (
            "celery.task.generate_audio",
            {"celery.task_name": "generate_audio"},
        )
    ]
