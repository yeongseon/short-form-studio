import logging
from importlib import import_module

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from shorts_api.app_factory import create_app
from shorts_api.middleware.telemetry import TelemetryMiddleware

from tests.auth_lookup_support import AuthDatabase, auth_db  # noqa: F401
from tests.middleware_app_support import ORIGIN, middleware_app  # noqa: F401


@pytest.mark.parametrize("key,status", [("personal-one", 200), ("invalid", 401)])
async def test_actual_app_preserves_telemetry_with_response_wrappers(
    middleware_app: FastAPI, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    key: str, status: int,
) -> None:
    # Given: actual telemetry middleware and SDK, isolated in-memory exporters.
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    telemetry = import_module("creator_service.telemetry")
    monkeypatch.setattr(TelemetryMiddleware, "_initialized", True)
    monkeypatch.setattr(telemetry, "get_tracer", tracer_provider.get_tracer)
    monkeypatch.setattr(telemetry, "get_meter", meter_provider.get_meter)
    monkeypatch.setenv("OTEL_ENABLED", "true")
    caplog.set_level(logging.INFO, logger="shorts_api.app_factory")
    try:
        # When
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            response = await client.get("/api/creator/projects", headers={
                "X-API-Key": key, "Origin": ORIGIN,
            })
        # Then
        assert response.status_code == status
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.attributes is not None
        assert span.attributes["http.status_code"] == status
        assert span.context is not None
        assert response.headers["x-trace-id"] == format(span.context.trace_id, "032x")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["access-control-allow-origin"] == ORIGIN
        data = reader.get_metrics_data()
        assert data is not None
        metrics = {metric.name: metric for resource in data.resource_metrics
                   for scope in resource.scope_metrics for metric in scope.metrics}
        counter = metrics["http.server.requests"].data.data_points
        assert len(counter) == 1
        assert counter[0].value == 1
        assert counter[0].attributes == {
            "method": "GET", "path": "/api/creator/projects", "status": str(status),
        }
        assert metrics["http.server.request.duration"].data.data_points[0].count == 1
        assert len([r for r in caplog.records if r.name == "shorts_api.app_factory"]) == 1
        assert not trace.get_current_span().get_span_context().is_valid
    finally:
        tracer_provider.shutdown()
        meter_provider.shutdown()
