"""Prometheus metrics for request, thread-pool, SQL and cache diagnostics."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import Request
from prometheus_client import Counter, Gauge, Histogram


ORDERS_CREATE_REQUESTS = Counter(
    "sirius_orders_create_requests",
    "Number of HTTP attempts to create an order.",
)
MENU_ITEMS_LATENCY = Histogram(
    "sirius_menu_items_request_duration_seconds",
    "Response time for GET /menu/items in seconds.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "sirius_http_requests_in_progress",
    "HTTP requests currently inside the application middleware.",
    labelnames=("method",),
)

THREADPOOL_TOTAL_TOKENS = Gauge(
    "sirius_threadpool_total_tokens",
    "Configured AnyIO default worker-thread limiter capacity.",
)
THREADPOOL_BORROWED_TOKENS = Gauge(
    "sirius_threadpool_borrowed_tokens",
    "AnyIO default worker-thread limiter tokens currently in use.",
)
THREADPOOL_WAITING_TASKS = Gauge(
    "sirius_threadpool_waiting_tasks",
    "Tasks currently waiting for an AnyIO default worker-thread token.",
)

DB_QUERY_DURATION = Histogram(
    "sirius_db_query_duration_seconds",
    "SQLAlchemy cursor execution duration, including database round-trip time.",
    labelnames=("operation",),
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
DB_QUERY_ERRORS = Counter(
    "sirius_db_query_errors",
    "SQLAlchemy cursor execution errors.",
    labelnames=("operation",),
)
DB_POOL_SIZE = Gauge("sirius_db_pool_size", "Configured SQLAlchemy connection pool size.")
DB_POOL_CHECKED_OUT = Gauge(
    "sirius_db_pool_checked_out", "SQLAlchemy connections currently checked out."
)
DB_POOL_CHECKED_IN = Gauge(
    "sirius_db_pool_checked_in", "SQLAlchemy connections currently idle in the pool."
)
DB_POOL_OVERFLOW = Gauge(
    "sirius_db_pool_overflow", "SQLAlchemy connections above the configured pool size."
)

MENU_CACHE_OPERATIONS = Counter(
    "sirius_menu_cache_operations",
    "Application menu-cache operations by operation and result.",
    labelnames=("operation", "result"),
)
MENU_CACHE_OPERATION_DURATION = Histogram(
    "sirius_menu_cache_operation_duration_seconds",
    "Duration of application menu-cache operations.",
    labelnames=("operation",),
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

_INSTRUMENTED_ENGINE_IDS: set[int] = set()


def configure_threadpool() -> int:
    """Configure AnyIO's shared default thread limiter and publish its capacity."""
    import anyio.to_thread

    raw_tokens = os.getenv("ANYIO_THREAD_TOKENS", "40")
    try:
        tokens = int(raw_tokens)
    except ValueError as exc:
        raise ValueError("ANYIO_THREAD_TOKENS must be a positive integer") from exc
    if tokens < 1:
        raise ValueError("ANYIO_THREAD_TOKENS must be a positive integer")

    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = tokens
    THREADPOOL_TOTAL_TOKENS.set(limiter.total_tokens)
    stats = limiter.statistics()
    THREADPOOL_BORROWED_TOKENS.set(stats.borrowed_tokens)
    THREADPOOL_WAITING_TASKS.set(stats.tasks_waiting)
    return tokens


async def sample_threadpool_metrics(interval_seconds: float = 0.5) -> None:
    """Continuously sample AnyIO thread-pool saturation and waiting tasks."""
    import anyio.to_thread

    limiter = anyio.to_thread.current_default_thread_limiter()
    while True:
        stats = limiter.statistics()
        THREADPOOL_TOTAL_TOKENS.set(stats.total_tokens)
        THREADPOOL_BORROWED_TOKENS.set(stats.borrowed_tokens)
        THREADPOOL_WAITING_TASKS.set(stats.tasks_waiting)
        await asyncio.sleep(interval_seconds)


def classify_sql_operation(statement: str) -> str:
    """Map SQL text to a bounded label; never export SQL text as a Prometheus label."""
    first_word = statement.lstrip().split(None, 1)
    operation = first_word[0].upper() if first_word else "OTHER"
    if operation in {"SELECT", "INSERT", "UPDATE", "DELETE", "CALL", "CREATE", "ALTER", "DROP"}:
        return operation
    return "OTHER"


def instrument_sqlalchemy_engine(engine: Any) -> None:
    """Attach low-cardinality query and pool metrics to a SQLAlchemy Engine."""
    from sqlalchemy import event

    engine_id = id(engine)
    if engine_id in _INSTRUMENTED_ENGINE_IDS:
        return
    _INSTRUMENTED_ENGINE_IDS.add(engine_id)

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._sirius_metrics_started_at = time.perf_counter()
        context._sirius_metrics_operation = classify_sql_operation(statement)

    def record_query(context) -> None:
        if context is None:
            return
        started_at = getattr(context, "_sirius_metrics_started_at", None)
        if started_at is None:
            return
        operation = getattr(context, "_sirius_metrics_operation", "OTHER")
        context._sirius_metrics_started_at = None
        DB_QUERY_DURATION.labels(operation=operation).observe(time.perf_counter() - started_at)

    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        record_query(context)

    def handle_error(exception_context):
        context = exception_context.execution_context
        if context is not None:
            operation = getattr(context, "_sirius_metrics_operation", "OTHER")
            DB_QUERY_ERRORS.labels(operation=operation).inc()
        record_query(context)

    def update_pool_metrics(*_args) -> None:
        pool = engine.pool
        for gauge, method_name, transform in (
            (DB_POOL_SIZE, "size", lambda value: value),
            (DB_POOL_CHECKED_OUT, "checkedout", lambda value: value),
            (DB_POOL_CHECKED_IN, "checkedin", lambda value: value),
            (DB_POOL_OVERFLOW, "overflow", lambda value: max(0, value)),
        ):
            method = getattr(pool, method_name, None)
            if callable(method):
                try:
                    gauge.set(transform(method()))
                except (AttributeError, TypeError):
                    pass

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    event.listen(engine, "handle_error", handle_error)
    for pool_event in ("connect", "checkout", "checkin", "close", "invalidate"):
        event.listen(engine, pool_event, update_pool_metrics)
    update_pool_metrics()


def record_menu_cache_operation(operation: str, result: str, started_at: float) -> None:
    """Record one menu-cache operation using bounded operation/result labels."""
    MENU_CACHE_OPERATIONS.labels(operation=operation, result=result).inc()
    MENU_CACHE_OPERATION_DURATION.labels(operation=operation).observe(
        max(0.0, time.perf_counter() - started_at)
    )


async def metrics_middleware(request: Request, call_next):
    path = request.url.path
    measure_menu = request.method == "GET" and path == "/menu/items"
    if request.method == "POST" and path == "/orders/create":
        ORDERS_CREATE_REQUESTS.inc()

    method = request.method if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE"} else "OTHER"
    in_progress = HTTP_REQUESTS_IN_PROGRESS.labels(method=method)
    in_progress.inc()
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        if measure_menu:
            MENU_ITEMS_LATENCY.observe(time.perf_counter() - started)
        raise
    finally:
        in_progress.dec()

    if measure_menu:
        MENU_ITEMS_LATENCY.observe(time.perf_counter() - started)
    return response
