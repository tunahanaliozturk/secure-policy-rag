"""Logs and traces. One tracer for the service; spans carry ids and counts, never question or answer text."""

import logging
from typing import Literal

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

tracer = trace.get_tracer("secure_policy_rag")

type TraceExporter = Literal["console", "none"]


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
