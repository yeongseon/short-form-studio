from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import context as otel_context
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_TELEMETRY_PATH = Path(__file__).resolve().parents[1] / "src/shorts_api/middleware/telemetry.py"
_telemetry_spec = spec_from_file_location("shorts_api.middleware.telemetry", _TELEMETRY_PATH)
assert _telemetry_spec is not None
assert _telemetry_spec.loader is not None
middleware_telemetry = module_from_spec(_telemetry_spec)
_telemetry_spec.loader.exec_module(middleware_telemetry)

_CREATOR_RUNS_UTILS_PATH = (
    Path(__file__).resolve().parents[1] / "src/shorts_api/routes/creator_runs_utils.py"
)
_creator_runs_utils_spec = spec_from_file_location(
    "shorts_api.routes.creator_runs_utils", _CREATOR_RUNS_UTILS_PATH
)
assert _creator_runs_utils_spec is not None
assert _creator_runs_utils_spec.loader is not None
creator_runs_utils = module_from_spec(_creator_runs_utils_spec)
_creator_runs_utils_spec.loader.exec_module(creator_runs_utils)

_CREATOR_SERVICE_TELEMETRY_PATH = (
    Path(__file__).resolve().parents[3] / "packages/creator-service/creator_service/telemetry.py"
)
_creator_service_telemetry_spec = spec_from_file_location(
    "creator_service.telemetry", _CREATOR_SERVICE_TELEMETRY_PATH
)
assert _creator_service_telemetry_spec is not None
assert _creator_service_telemetry_spec.loader is not None
creator_service_telemetry = module_from_spec(_creator_service_telemetry_spec)
sys.modules["creator_service.telemetry"] = creator_service_telemetry
_creator_service_telemetry_spec.loader.exec_module(creator_service_telemetry)


@pytest.fixture
def instrumented_client(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    monkeypatch.setenv("OTEL_ENABLED", "true")

    class _NoopCounter:
        def add(self, _value, attributes=None):
            return None

    class _NoopHistogram:
        def record(self, _value, attributes=None):
            return None

    class _NoopMeter:
        def create_counter(self, _name, unit=None, description=None):
            return _NoopCounter()

        def create_histogram(self, _name, unit=None, description=None):
            return _NoopHistogram()

    class _TelemetryProxy:
        def init_telemetry(self, _service_name: str) -> None:
            return None

        def get_meter(self, _name: str):
            return _NoopMeter()

        def get_tracer(self, name: str):
            return provider.get_tracer(name)

    monkeypatch.setattr(middleware_telemetry, "import_module", lambda _name: _TelemetryProxy())

    middleware_telemetry.TelemetryMiddleware._initialized = False
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(middleware_telemetry.TelemetryMiddleware)
    client = TestClient(app)

    yield client, exporter

    exporter.shutdown()


def test_fastapi_instrumentation_emits_http_spans(instrumented_client):
    client, exporter = instrumented_client

    response = client.get("/health")
    assert response.status_code == 200

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1

    http_span = spans[-1]
    assert http_span.name == "GET /health"

    attrs = dict(http_span.attributes)
    assert attrs["http.method"] == "GET"
    assert attrs["http.route"] == "/health"
    assert attrs["http.status_code"] == 200


def test_fastapi_instrumentation_sets_trace_id_header(instrumented_client):
    client, exporter = instrumented_client

    response = client.get("/health")
    assert response.status_code == 200

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1

    http_span = spans[-1]
    assert response.headers.get("X-Trace-Id") == format(http_span.context.trace_id, "032x")


def test_api_to_celery_trace_context_propagates_via_task_headers(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    captured_headers: dict[str, str] = {}

    class _FakeAsyncResult:
        id = "task-123"

    class _FakeTask:
        def apply_async(self, *, args=None, kwargs=None, headers=None):
            del args, kwargs
            captured_headers.update(headers or {})
            return _FakeAsyncResult()

    fake_tasks_module = types.SimpleNamespace(generate_script=_FakeTask())
    monkeypatch.setattr(
        "creator_service.task_dispatch_service.import_module",
        lambda name: creator_service_telemetry
        if name == "creator_service.telemetry"
        else fake_tasks_module
        if name == "tasks.generate_script"
        else None,
    )

    incoming_trace_id = "0af7651916cd43dd8448eb211c80319c"
    incoming_headers = {
        "traceparent": f"00-{incoming_trace_id}-b7ad6b7169203331-01",
    }

    parent_context = extract(incoming_headers)
    token = otel_context.attach(parent_context)
    with tracer.start_as_current_span("api-request", kind=SpanKind.SERVER):
        creator_runs_utils.dispatch_generate_script(1, "idea", "model", None)
    otel_context.detach(token)

    assert "traceparent" in captured_headers
    assert incoming_trace_id in captured_headers["traceparent"]
