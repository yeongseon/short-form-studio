"""Unit tests for telemetry middleware.

This module validates the TelemetryMiddleware behavior in isolation using
fake tracer and meter implementations. It tests:
- Lazy initialization of telemetry instruments
- HTTP attribute capture (target, route, status code, latency)
- Query parameter exclusion and numeric ID normalization

NOTE: These are UNIT tests using mock tracer/meter. They validate middleware
behavior in isolation only.

Full API-to-worker trace propagation testing (verifying that traces are
correctly created by the API middleware AND propagated to Celery workers via
OTEL context) requires a running OTEL collector and instrumented Celery worker
environment. See test_telemetry_integration.py for the full propagation test plan.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.responses import Response

_TELEMETRY_PATH = Path(__file__).resolve().parents[1] / "src/shorts_api/middleware/telemetry.py"
_telemetry_spec = spec_from_file_location("shorts_api.middleware.telemetry", _TELEMETRY_PATH)
assert _telemetry_spec is not None
assert _telemetry_spec.loader is not None
middleware_telemetry = module_from_spec(_telemetry_spec)
_telemetry_spec.loader.exec_module(middleware_telemetry)


class _FakeSpan:
    def __init__(self, captured_attrs: dict[str, str]) -> None:
        self._captured_attrs = captured_attrs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def set_attribute(self, key: str, value) -> None:
        self._captured_attrs[key] = value

    def get_span_context(self):
        class _Ctx:
            is_valid = True
            trace_id = int("abcd", 16)

        return _Ctx()


class _FakeTracer:
    def __init__(self, captured_attrs: dict[str, str]) -> None:
        self._captured_attrs = captured_attrs

    def start_as_current_span(self, _name: str, attributes: dict[str, str]):
        self._captured_attrs.update(attributes)
        return _FakeSpan(self._captured_attrs)


class _FakeMeter:
    def __init__(self) -> None:
        self.counter_created = 0
        self.histogram_created = 0

    def create_counter(self, _name: str, **_kwargs):
        self.counter_created += 1

        class _Counter:
            def add(self, _value: int | float, attributes=None) -> None:
                return None

        return _Counter()

    def create_histogram(self, _name: str, **_kwargs):
        self.histogram_created += 1

        class _Histogram:
            def record(self, _value: int | float, attributes=None) -> None:
                return None

        return _Histogram()


class _FakeTelemetry:
    def __init__(self, captured_attrs: dict[str, str]) -> None:
        self.init_calls = 0
        self.meter = _FakeMeter()
        self.tracer = _FakeTracer(captured_attrs)

    def init_telemetry(self, _service_name: str) -> None:
        self.init_calls += 1

    def get_meter(self, _name: str):
        return self.meter

    def get_tracer(self, _name: str):
        return self.tracer


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/items",
            "query_string": b"token=secret",
            "headers": [],
            "client": ("127.0.0.1", 8080),
            "server": ("test", 80),
        }
    )


@pytest.mark.asyncio
async def test_instruments_created_lazily(monkeypatch) -> None:
    middleware_telemetry.TelemetryMiddleware._initialized = False
    captured_attrs: dict[str, str] = {}
    fake = _FakeTelemetry(captured_attrs)
    monkeypatch.setattr(middleware_telemetry, "import_module", lambda _name: fake)
    middleware = middleware_telemetry.TelemetryMiddleware(app=lambda *_args, **_kwargs: None)

    assert fake.meter.counter_created == 0
    assert fake.meter.histogram_created == 0

    async def _call_next(_request: Request) -> Response:
        return Response(status_code=200)

    await middleware.dispatch(_request(), _call_next)

    assert fake.meter.counter_created == 1
    assert fake.meter.histogram_created == 1


@pytest.mark.asyncio
async def test_http_target_excludes_query_params(monkeypatch) -> None:
    middleware_telemetry.TelemetryMiddleware._initialized = False
    captured_attrs: dict[str, str] = {}
    fake = _FakeTelemetry(captured_attrs)
    monkeypatch.setattr(middleware_telemetry, "import_module", lambda _name: fake)
    middleware = middleware_telemetry.TelemetryMiddleware(app=lambda *_args, **_kwargs: None)

    async def _call_next(_request: Request) -> Response:
        return Response(status_code=204)

    await middleware.dispatch(_request(), _call_next)

    assert captured_attrs["http.target"] == "/items"


@pytest.mark.asyncio
async def test_http_route_normalizes_numeric_ids(monkeypatch) -> None:
    middleware_telemetry.TelemetryMiddleware._initialized = False
    captured_attrs: dict[str, str] = {}
    fake = _FakeTelemetry(captured_attrs)
    monkeypatch.setattr(middleware_telemetry, "import_module", lambda _name: fake)
    middleware = middleware_telemetry.TelemetryMiddleware(app=lambda *_args, **_kwargs: None)

    req = Request(
        {
            "type": "http", "http_version": "1.1", "method": "GET",
            "scheme": "http", "path": "/api/creator/runs/123/artifacts/456/download",
            "query_string": b"", "headers": [],
            "client": ("127.0.0.1", 8080), "server": ("test", 80),
        }
    )

    async def _call_next(_request: Request) -> Response:
        return Response(status_code=200)

    await middleware.dispatch(req, _call_next)

    assert captured_attrs["http.route"] == "/api/creator/runs/{id}/artifacts/{id}/download"
    assert captured_attrs["http.target"] == "/api/creator/runs/123/artifacts/456/download"
