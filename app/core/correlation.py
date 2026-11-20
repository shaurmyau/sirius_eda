"""Сквозной correlation_id для HTTP-запросов и фоновых consumer'ов."""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar, Token

import structlog
from fastapi import Request

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
log = structlog.get_logger("http")


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> Token:
    return _correlation_id.set(value)


def reset_correlation_id(token: Token) -> None:
    _correlation_id.reset(token)


async def correlation_id_middleware(request: Request, call_next):
    """Принимает/создаёт ID, привязывает его к логам и возвращает клиенту."""
    supplied = request.headers.get("X-Correlation-ID", "").strip()
    correlation_id = supplied[:128] if supplied else str(uuid.uuid4())
    token = set_correlation_id(correlation_id)
    request.state.correlation_id = correlation_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

    try:
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            if span and span.is_recording():
                span.set_attribute("correlation_id", correlation_id)
        except Exception:
            pass

        try:
            import sentry_sdk
            sentry_sdk.set_tag("correlation_id", correlation_id)
        except Exception:
            pass

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                correlation_id=correlation_id,
            )
            raise

        response.headers["X-Correlation-ID"] = correlation_id
        log.info(
            "http_request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            correlation_id=correlation_id,
        )
        return response
    finally:
        structlog.contextvars.clear_contextvars()
        reset_correlation_id(token)
