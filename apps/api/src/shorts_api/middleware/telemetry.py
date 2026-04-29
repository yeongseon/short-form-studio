from __future__ import annotations

import time
from importlib import import_module
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TelemetryMiddleware(BaseHTTPMiddleware):
    _lock = Lock()
    _initialized = False

    def __init__(self, app) -> None:
        super().__init__(app)
        self._request_counter = None
        self._request_latency = None

    @classmethod
    def _ensure_init(cls) -> None:
        if cls._initialized:
            return
        with cls._lock:
            if cls._initialized:
                return
            _telemetry().init_telemetry("short-form-studio-api")
            cls._initialized = True

    async def dispatch(self, request: Request, call_next) -> Response:
        self._ensure_init()
        if self._request_counter is None or self._request_latency is None:
            meter = _telemetry().get_meter("shorts_api.middleware.telemetry")
            self._request_counter = meter.create_counter(
                "http.server.requests",
                unit="1",
                description="Count of incoming HTTP requests",
            )
            self._request_latency = meter.create_histogram(
                "http.server.request.duration",
                unit="ms",
                description="Request latency in milliseconds",
            )

        tracer = _telemetry().get_tracer("shorts_api.middleware.telemetry")

        start = time.perf_counter()
        status_code = 500
        route_path = request.url.path

        with tracer.start_as_current_span(
            f"{request.method} {route_path}",
            attributes={
                "http.method": request.method,
                "http.route": route_path,
                "http.target": request.url.path,
            },
        ) as span:
            response = await call_next(request)
            status_code = response.status_code
            if span is not None and hasattr(span, "set_attribute"):
                span.set_attribute("http.status_code", status_code)

        duration_ms = (time.perf_counter() - start) * 1000
        metric_attrs = {
            "method": request.method,
            "path": route_path,
            "status": str(status_code),
        }
        self._request_counter.add(1, attributes=metric_attrs)
        self._request_latency.record(duration_ms, attributes=metric_attrs)

        trace_id = ""
        current_span = span if span is not None else None
        if current_span is not None and hasattr(current_span, "get_span_context"):
            span_context = current_span.get_span_context()
            if span_context is not None and getattr(span_context, "is_valid", False):
                trace_id = format(span_context.trace_id, "032x")
        response.headers["X-Trace-Id"] = trace_id
        return response


def _telemetry():
    return import_module("creator_service.telemetry")
