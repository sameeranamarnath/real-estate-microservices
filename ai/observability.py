"""Tracing for the agent.

Emits OpenTelemetry spans using the GenAI semantic conventions when the OTel SDK
is present, and degrades to a no-op when it is not, so the service never fails to
start because tracing is missing.

Set OTEL_EXPORTER_OTLP_ENDPOINT to ship spans to a collector (Langfuse,
Jaeger, Grafana Tempo, Honeycomb - anything OTLP-compatible).
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

try:  # pragma: no cover - exercised only when the optional extra is installed
    from opentelemetry import trace as _otel_trace

    OTEL_AVAILABLE = True
except Exception:  # pragma: no cover
    _otel_trace = None
    OTEL_AVAILABLE = False

_tracer: Any = None


@dataclass
class SpanRecord:
    """What every run reports, with or without an exporter attached."""

    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None


def configure(service_name: str = "sql-agent", service_version: str = "1.0.0") -> bool:
    """Wire the global tracer provider. Returns False when OTel is not installed."""
    global _tracer
    if not OTEL_AVAILABLE:
        return False
    try:  # pragma: no cover - depends on optional packages
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
                "deployment.environment": os.getenv("DEPLOY_ENV", "local"),
            }
        )
        provider = TracerProvider(resource=resource)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        _otel_trace.set_tracer_provider(provider)
        _tracer = _otel_trace.get_tracer(service_name, service_version)
        return True
    except Exception:
        _tracer = None
        return False


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[SpanRecord]:
    """Time a unit of work and record GenAI-convention attributes on it.

    Yields a mutable record so callers can attach token counts discovered inside
    the block.
    """
    record = SpanRecord(name=name, attributes=dict(attributes))
    started = time.perf_counter()
    otel_span = _tracer.start_span(name, attributes=attributes) if _tracer else None
    try:
        yield record
    except Exception as exc:
        record.error = f"{type(exc).__name__}: {exc}"
        if otel_span is not None:
            otel_span.record_exception(exc)
        raise
    finally:
        record.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        if otel_span is not None:
            for key, value in record.attributes.items():
                otel_span.set_attribute(key, value)
            otel_span.set_attribute("duration_ms", record.duration_ms)
            if record.error:
                otel_span.set_attribute("error", record.error)
            otel_span.end()


def genai_attributes(
    model: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    operation: str = "chat",
    system: str = "openai-compatible",
) -> dict[str, Any]:
    """OpenTelemetry GenAI semantic-convention attribute names."""
    return {
        "gen_ai.system": system,
        "gen_ai.operation.name": operation,
        "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": prompt_tokens,
        "gen_ai.usage.output_tokens": completion_tokens,
    }
