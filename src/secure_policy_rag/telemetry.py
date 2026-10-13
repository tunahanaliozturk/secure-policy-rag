"""Logs and traces. One tracer for the service; spans carry ids and counts, never question or answer text."""

import logging
from typing import Literal

import structlog
from fastapi.telemetry import TelemetryConfig
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

tracer = trace.get_tracer("secure_policy_rag")

type TraceExporter = Literal["console", "none"]

# FastAPI traces every request by itself when a tracer provider exists, and puts the path and the query string of the
# request on the span; it can also export validation and exception messages, and pick up an exporter from the
# environment. All of that is text the caller chose, and this service's spans carry ids, counts and outcomes only. So
# the framework's own tracing and logging are off in both apps, and the spans are the ones pipeline.py opens.
FRAMEWORK_TELEMETRY: TelemetryConfig = {"tracing": False, "logs": False, "auto_configure": False}


def configure(level: str, exporter: TraceExporter) -> None:
    """JSON logs on stdout. Spans go to the console exporter by default; an OTLP exporter is a two-line change here
    once there is a collector to send them to."""
    logging.basicConfig(format="%(message)s", level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level.upper()]),
        cache_logger_on_first_use=True,
    )
    if exporter == "console":
        provider = TracerProvider(resource=Resource.create({"service.name": "secure-policy-rag"}))
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
