from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    old_provider = trace.get_tracer_provider()
    with (
        patch("opentelemetry.trace._TRACER_PROVIDER", None),
        patch("opentelemetry.trace._TRACER_PROVIDER_SET_ONCE") as once,
    ):
        once.do_once.side_effect = lambda func: func()
        trace.set_tracer_provider(provider)
        yield exporter

    with (
        patch("opentelemetry.trace._TRACER_PROVIDER", provider),
        patch("opentelemetry.trace._TRACER_PROVIDER_SET_ONCE") as once,
    ):
        once.do_once.side_effect = lambda func: func()
        trace.set_tracer_provider(old_provider)

    exporter.shutdown()


def test_tracer_emits_spans(span_exporter):
    tracer = trace.get_tracer("test-tracer")

    with tracer.start_as_current_span("test-operation") as span:
        span.set_attribute("test.key", "test-value")

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test-operation"
    assert spans[0].attributes["test.key"] == "test-value"


def test_nested_spans_preserve_context(span_exporter):
    tracer = trace.get_tracer("test-tracer")

    with tracer.start_as_current_span("parent"):
        with tracer.start_as_current_span("child"):
            pass

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 2

    child = next(span for span in spans if span.name == "child")
    parent = next(span for span in spans if span.name == "parent")
    assert child.context.trace_id == parent.context.trace_id
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id
