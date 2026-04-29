from __future__ import annotations

import functools
import logging
import os
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any


class _NoOpTracer:
    def start_as_current_span(self, _name: str, **_kwargs: Any):
        return nullcontext()


@dataclass
class _TelemetryState:
    initialized: bool = False
    enabled: bool = False


_STATE = _TelemetryState()


def _is_enabled() -> bool:
    value = os.getenv("OTEL_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def init_telemetry(service_name: str) -> None:
    if _STATE.initialized:
        return

    _STATE.initialized = True
    _STATE.enabled = _is_enabled()
    if _STATE.enabled:
        logging.getLogger(__name__).info("OpenTelemetry enabled for %s", service_name)


def get_tracer(name: str):
    if not _STATE.enabled:
        return _NoOpTracer()

    try:
        from opentelemetry import trace
    except ImportError:
        return _NoOpTracer()

    return trace.get_tracer(name)


def trace_task(task_name: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer(__name__)
            with tracer.start_as_current_span(
                f"celery.task.{task_name}",
                attributes={"celery.task_name": task_name},
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator
