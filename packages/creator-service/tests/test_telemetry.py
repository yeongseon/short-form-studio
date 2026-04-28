from __future__ import annotations

import importlib

from creator_service import telemetry


class _FakeSpanContext:
    def __init__(self) -> None:
        self.trace_id = int("1234", 16)
        self.span_id = int("5678", 16)
        self.is_valid = True


class _FakeSpan:
    def get_span_context(self) -> _FakeSpanContext:
        return _FakeSpanContext()


class _FakeTraceModule:
    def __init__(self) -> None:
        self.provider = None

    def set_tracer_provider(self, provider) -> None:
        self.provider = provider

    def get_tracer(self, _name: str):
        return object()

    def get_current_span(self):
        return _FakeSpan()


class _FakeMetricsModule:
    def __init__(self) -> None:
        self.provider = None

    def set_meter_provider(self, provider) -> None:
        self.provider = provider

    def get_meter(self, _name: str):
        return object()


def _fake_otel_map() -> dict:
    trace_mod = _FakeTraceModule()
    metrics_mod = _FakeMetricsModule()

    class _Resource:
        @staticmethod
        def create(attributes):
            return attributes

    class _TracerProvider:
        def __init__(self, resource):
            self.resource = resource
            self.processors = []

        def add_span_processor(self, processor):
            self.processors.append(processor)

    class _BatchSpanProcessor:
        def __init__(self, exporter):
            self.exporter = exporter

    class _SimpleSpanProcessor:
        def __init__(self, exporter):
            self.exporter = exporter

    class _ConsoleSpanExporter:
        pass

    class _OTLPSpanExporter:
        def __init__(self, endpoint):
            self.endpoint = endpoint

    class _PeriodicExportingMetricReader:
        def __init__(self, exporter):
            self.exporter = exporter

    class _ConsoleMetricExporter:
        pass

    class _OTLPMetricExporter:
        def __init__(self, endpoint):
            self.endpoint = endpoint

    class _MeterProvider:
        def __init__(self, resource, metric_readers):
            self.resource = resource
            self.metric_readers = metric_readers

    class _LoggerProvider:
        def __init__(self, resource):
            self.resource = resource
            self.processors = []

        def add_log_record_processor(self, processor):
            self.processors.append(processor)

    class _BatchLogRecordProcessor:
        def __init__(self, exporter):
            self.exporter = exporter

    class _SimpleLogRecordProcessor:
        def __init__(self, exporter):
            self.exporter = exporter

    class _ConsoleLogExporter:
        pass

    class _OTLPLogExporter:
        def __init__(self, endpoint):
            self.endpoint = endpoint

    return {
        "metrics": metrics_mod,
        "trace": trace_mod,
        "LoggerProvider": _LoggerProvider,
        "BatchLogRecordProcessor": _BatchLogRecordProcessor,
        "ConsoleLogExporter": _ConsoleLogExporter,
        "SimpleLogRecordProcessor": _SimpleLogRecordProcessor,
        "MeterProvider": _MeterProvider,
        "ConsoleMetricExporter": _ConsoleMetricExporter,
        "PeriodicExportingMetricReader": _PeriodicExportingMetricReader,
        "Resource": _Resource,
        "TracerProvider": _TracerProvider,
        "BatchSpanProcessor": _BatchSpanProcessor,
        "ConsoleSpanExporter": _ConsoleSpanExporter,
        "SimpleSpanProcessor": _SimpleSpanProcessor,
        "INVALID_SPAN_CONTEXT": object(),
        "OTLPLogExporter": _OTLPLogExporter,
        "OTLPMetricExporter": _OTLPMetricExporter,
        "OTLPSpanExporter": _OTLPSpanExporter,
    }


def _reset_state() -> None:
    telemetry._STATE.initialized = False
    telemetry._STATE.enabled = False


def test_init_telemetry_noop_when_disabled(monkeypatch) -> None:
    _reset_state()
    monkeypatch.setenv("OTEL_ENABLED", "false")
    telemetry.init_telemetry("svc")
    assert telemetry._STATE.initialized is True
    assert telemetry._STATE.enabled is False


def test_init_telemetry_enabled_sets_providers(monkeypatch) -> None:
    _reset_state()
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    fake = _fake_otel_map()
    monkeypatch.setattr(telemetry, "_load_otel", lambda: fake)

    telemetry.init_telemetry("svc")

    assert telemetry._STATE.enabled is True
    assert fake["trace"].provider is not None
    assert fake["metrics"].provider is not None


def test_get_tracer_returns_tracer(monkeypatch) -> None:
    _reset_state()
    telemetry._STATE.enabled = True
    fake = _fake_otel_map()
    monkeypatch.setattr(telemetry, "_load_otel", lambda: fake)
    tracer = telemetry.get_tracer("svc")
    assert tracer is not None


def test_get_meter_returns_meter(monkeypatch) -> None:
    _reset_state()
    telemetry._STATE.enabled = True
    fake = _fake_otel_map()
    monkeypatch.setattr(telemetry, "_load_otel", lambda: fake)
    meter = telemetry.get_meter("svc")
    assert meter is not None


def test_add_trace_context_to_log_adds_ids(monkeypatch) -> None:
    _reset_state()
    telemetry._STATE.enabled = True
    fake = _fake_otel_map()
    monkeypatch.setattr(telemetry, "_load_otel", lambda: fake)

    enriched = telemetry.add_trace_context_to_log({"message": "ok"})

    assert enriched["trace_id"] == format(int("1234", 16), "032x")
    assert enriched["span_id"] == format(int("5678", 16), "016x")


def test_graceful_degradation_when_otel_missing(monkeypatch) -> None:
    module = importlib.reload(telemetry)
    module._STATE.initialized = False
    module._STATE.enabled = False
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setattr(module, "_load_otel", lambda: None)

    module.init_telemetry("svc")

    tracer = module.get_tracer("svc")
    meter = module.get_meter("svc")
    enriched = module.add_trace_context_to_log({"k": "v"})

    assert module._STATE.enabled is False
    assert hasattr(tracer, "start_as_current_span")
    assert hasattr(meter, "create_counter")
    assert enriched == {"k": "v"}


def test_load_otel_handles_import_error(monkeypatch) -> None:
    module = importlib.reload(telemetry)

    import builtins

    real_import = builtins.__import__

    def _mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("opentelemetry"):
            raise ImportError
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _mock_import)

    assert module._load_otel() is None
