from __future__ import annotations

import logging
import os
from contextlib import nullcontext
from dataclasses import dataclass
from importlib import import_module
from typing import Any


class _NoOpInstrument:
    def add(self, _value: int | float, _attributes: dict[str, str] | None = None) -> None:
        return None

    def record(self, _value: int | float, _attributes: dict[str, str] | None = None) -> None:
        return None


class _NoOpMeter:
    def create_counter(self, _name: str, **_kwargs: Any) -> _NoOpInstrument:
        return _NoOpInstrument()

    def create_histogram(self, _name: str, **_kwargs: Any) -> _NoOpInstrument:
        return _NoOpInstrument()


class _NoOpTracer:
    def start_as_current_span(self, _name: str, **_kwargs: Any):
        return nullcontext()


@dataclass
class _TelemetryState:
    initialized: bool = False
    enabled: bool = False


_STATE = _TelemetryState()


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        enriched = add_trace_context_to_log({})
        for key, value in enriched.items():
            setattr(record, key, value)
        return True


def _is_enabled() -> bool:
    value = os.getenv("OTEL_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _load_otel() -> dict[str, Any] | None:
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import (
            BatchLogRecordProcessor,
            ConsoleLogExporter,
            SimpleLogRecordProcessor,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
        from opentelemetry.trace.span import INVALID_SPAN_CONTEXT

        otlp_log_exporter = None
        otlp_metric_exporter = None
        otlp_span_exporter = None
        try:
            otlp_log_exporter = import_module(
                "opentelemetry.exporter.otlp.proto.grpc._log_exporter"
            ).OTLPLogExporter
            otlp_metric_exporter = import_module(
                "opentelemetry.exporter.otlp.proto.grpc.metric_exporter"
            ).OTLPMetricExporter
            otlp_span_exporter = import_module(
                "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"
            ).OTLPSpanExporter
        except ImportError:
            pass

        return {
            "metrics": metrics,
            "trace": trace,
            "LoggerProvider": LoggerProvider,
            "BatchLogRecordProcessor": BatchLogRecordProcessor,
            "ConsoleLogExporter": ConsoleLogExporter,
            "SimpleLogRecordProcessor": SimpleLogRecordProcessor,
            "MeterProvider": MeterProvider,
            "ConsoleMetricExporter": ConsoleMetricExporter,
            "PeriodicExportingMetricReader": PeriodicExportingMetricReader,
            "Resource": Resource,
            "TracerProvider": TracerProvider,
            "BatchSpanProcessor": BatchSpanProcessor,
            "ConsoleSpanExporter": ConsoleSpanExporter,
            "SimpleSpanProcessor": SimpleSpanProcessor,
            "INVALID_SPAN_CONTEXT": INVALID_SPAN_CONTEXT,
            "OTLPLogExporter": otlp_log_exporter,
            "OTLPMetricExporter": otlp_metric_exporter,
            "OTLPSpanExporter": otlp_span_exporter,
        }
    except ImportError:
        return None


def init_telemetry(service_name: str) -> None:
    if _STATE.initialized:
        return

    _STATE.initialized = True
    root_logger = logging.getLogger()
    if not any(isinstance(existing, TraceContextFilter) for existing in root_logger.filters):
        root_logger.addFilter(TraceContextFilter())

    if not _is_enabled():
        _STATE.enabled = False
        return

    otel = _load_otel()
    if otel is None:
        _STATE.enabled = False
        return

    environment = os.getenv("OTEL_ENVIRONMENT", "development")
    configured_service_name = os.getenv("OTEL_SERVICE_NAME", service_name)
    service_version = os.getenv("OTEL_SERVICE_VERSION", "unknown")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    is_otlp = bool(endpoint)

    resource = otel["Resource"].create(
        {
            "service.name": configured_service_name,
            "service.version": service_version,
            "deployment.environment": environment,
        }
    )

    tracer_provider = otel["TracerProvider"](resource=resource)
    if is_otlp and otel["OTLPSpanExporter"] is not None:
        span_exporter = otel["OTLPSpanExporter"](endpoint=endpoint)
        tracer_provider.add_span_processor(otel["BatchSpanProcessor"](span_exporter))
    else:
        tracer_provider.add_span_processor(
            otel["SimpleSpanProcessor"](otel["ConsoleSpanExporter"]())
        )
    otel["trace"].set_tracer_provider(tracer_provider)

    metric_readers = []
    if is_otlp and otel["OTLPMetricExporter"] is not None:
        metric_readers.append(
            otel["PeriodicExportingMetricReader"](otel["OTLPMetricExporter"](endpoint=endpoint))
        )
    else:
        metric_readers.append(
            otel["PeriodicExportingMetricReader"](otel["ConsoleMetricExporter"]())
        )
    meter_provider = otel["MeterProvider"](resource=resource, metric_readers=metric_readers)
    otel["metrics"].set_meter_provider(meter_provider)

    logger_provider = otel["LoggerProvider"](resource=resource)
    if is_otlp and otel["OTLPLogExporter"] is not None:
        logger_provider.add_log_record_processor(
            otel["BatchLogRecordProcessor"](otel["OTLPLogExporter"](endpoint=endpoint))
        )
    else:
        logger_provider.add_log_record_processor(
            otel["SimpleLogRecordProcessor"](otel["ConsoleLogExporter"]())
        )

    _STATE.enabled = True


def get_tracer(name: str):
    if not _STATE.enabled:
        return _NoOpTracer()
    otel = _load_otel()
    if otel is None:
        return _NoOpTracer()
    return otel["trace"].get_tracer(name)


def get_meter(name: str):
    if not _STATE.enabled:
        return _NoOpMeter()
    otel = _load_otel()
    if otel is None:
        return _NoOpMeter()
    return otel["metrics"].get_meter(name)


def add_trace_context_to_log(record: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(record)
    if not _STATE.enabled:
        return enriched

    otel = _load_otel()
    if otel is None:
        return enriched

    span = otel["trace"].get_current_span()
    if span is None:
        return enriched

    span_context = span.get_span_context()
    if span_context is None or span_context == otel["INVALID_SPAN_CONTEXT"]:
        return enriched

    if getattr(span_context, "is_valid", False):
        enriched["trace_id"] = format(span_context.trace_id, "032x")
        enriched["span_id"] = format(span_context.span_id, "016x")
    return enriched
