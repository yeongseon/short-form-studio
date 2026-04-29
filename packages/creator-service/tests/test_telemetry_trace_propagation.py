from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult, SpanExporter


class _CollectingSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS


def test_trace_context_propagates_from_parent_to_child() -> None:
    """Unit-level trace context verification within one process.

    This test confirms parent/child span linkage in-process. End-to-end API-to-worker
    propagation requires an integration environment and is intentionally out of scope
    for this unit test.
    """
    exporter = _CollectingSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("parent") as parent:
        with tracer.start_as_current_span("child"):
            pass

    parent_span = next(span for span in exporter.spans if span.name == "parent")
    child_span = next(span for span in exporter.spans if span.name == "child")

    assert child_span.context.trace_id == parent.get_span_context().trace_id
    assert child_span.parent is not None
    assert child_span.parent.span_id == parent_span.context.span_id
