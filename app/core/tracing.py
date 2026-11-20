"""OpenTelemetry: FastAPI + ручные spans для RabbitMQ publisher/consumer."""
from __future__ import annotations

import logging
import os

log = logging.getLogger("observability.tracing")
_initialized = False


def setup_tracing(app=None, service_name: str | None = None) -> bool:
    """Подключает OTLP exporter и, при передаче app, FastAPI instrumentation."""
    global _initialized
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    enabled = os.getenv("OTEL_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if not _initialized:
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
            service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "sirius-app")
            provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": service_name,
                        "service.namespace": "sirius-eda",
                        "deployment.environment.name": os.getenv("SENTRY_ENVIRONMENT", "development"),
                    }
                )
            )
            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                insecure=not endpoint.startswith("https://"),
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            _initialized = True
            log.info("OpenTelemetry настроен", service_name=service_name, endpoint=endpoint)

        if app is not None and not getattr(app.state, "otel_instrumented", False):
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app, excluded_urls=r".*/metrics$")
            app.state.otel_instrumented = True
        return True
    except Exception:
        log.exception("OpenTelemetry не удалось включить; приложение продолжит работу")
        return False


def get_tracer(name: str = "sirius-eda"):
    from opentelemetry import trace
    return trace.get_tracer(name)
