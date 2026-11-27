"""Общий каркас consumer'ов RabbitMQ.

Гарантии:
* ack ставится только после успешной обработки (at-least-once);
* при ошибке сообщение возвращается в очередь ОДИН раз; если и вторая попытка
  неудачна (`reject_on_redelivered`) — reject без requeue → dead-letter exchange
  → DLQ. «Битое» сообщение не блокирует очередь;
* исходящие события (шаг саги) публикуются после коммита транзакции.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.core.rabbitmq import QueueDef, declare_topology, get_connection, publish_event
from app.workers.handlers import OutEvent
from app.core.correlation import set_correlation_id, reset_correlation_id
from app.core.logging import setup_logging
from app.core.sentry import setup_sentry
from app.core.tracing import setup_tracing, get_tracer
from opentelemetry import propagate
from opentelemetry.trace import SpanKind, Status, StatusCode
import structlog

log = structlog.get_logger("workers")

Handler = Callable[[object, dict], list[OutEvent]]


@dataclass(frozen=True)
class ConsumerSpec:
    name: str
    queue: QueueDef
    handler: Handler
    ready_message: str = ""


def make_processor(spec: ConsumerSpec, session_factory, exchange):
    async def on_message(message) -> None:
        headers = message.headers or {}
        correlation_id = str(headers.get("X-Correlation-ID") or "unknown")
        token = set_correlation_id(correlation_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            service=f"{spec.name}-consumer",
        )
        parent_context = propagate.extract(headers)
        tracer = get_tracer(f"sirius.worker.{spec.name}")

        try:
            with tracer.start_as_current_span(
                f"{spec.name}.consume",
                context=parent_context,
                kind=SpanKind.CONSUMER,
            ) as span:
                span.set_attribute("messaging.system", "rabbitmq")
                span.set_attribute("messaging.destination.name", spec.queue.name)
                span.set_attribute("messaging.operation", "process")
                if message.message_id:
                    span.set_attribute("messaging.message.id", str(message.message_id))

                try:
                    async with message.process(requeue=True, reject_on_redelivered=True):
                        payload = json.loads(message.body)
                        if not isinstance(payload, dict):
                            raise ValueError("payload должен быть JSON-объектом")
                        # Routing key помогает одному consumer-у отличать OrderPaid от OrderCancelled.
                        payload.setdefault("_routing_key", getattr(message, "routing_key", ""))
                        if payload.get("order_id") is not None:
                            span.set_attribute("order.id", str(payload["order_id"]))

                        log.info(
                            "message_received",
                            consumer=spec.name,
                            queue=spec.queue.name,
                            order_id=payload.get("order_id"),
                            event_id=payload.get("event_id"),
                            correlation_id=correlation_id,
                        )

                        db = session_factory()
                        try:
                            outgoing = spec.handler(db, payload)
                        except Exception:
                            db.rollback()
                            raise
                        finally:
                            db.close()

                        for routing_key, body in outgoing:
                            await publish_event(routing_key, body, exchange=exchange)

                    log.info(
                        "message_processed",
                        consumer=spec.name,
                        queue=spec.queue.name,
                        correlation_id=correlation_id,
                    )
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
        except Exception as exc:  # сообщение уже nack'нуто / отправлено в DLQ
            try:
                import sentry_sdk
                sentry_sdk.set_tag("correlation_id", correlation_id)
                sentry_sdk.capture_exception(exc)
            except Exception:
                pass
            log.exception(
                "message_processing_failed",
                consumer=spec.name,
                queue=spec.queue.name,
                redelivered=message.redelivered,
                error=str(exc),
                correlation_id=correlation_id,
            )
        finally:
            structlog.contextvars.clear_contextvars()
            reset_correlation_id(token)

    return on_message

async def start_consumer(channel, spec: ConsumerSpec, session_factory=None):
    """Объявляет топологию и подписывает consumer на его очередь."""
    if session_factory is None:
        from app.database import SessionLocal
        session_factory = SessionLocal
    exchange, queues = await declare_topology(channel)
    queue = queues[spec.queue.name]
    await queue.consume(make_processor(spec, session_factory, exchange))
    return queue


async def _connect_with_retry(attempts: int = 30, delay: float = 2.0):
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return await get_connection()
        except Exception as exc:  # RabbitMQ ещё поднимается
            last = exc
            print(f"[{__name__}] RabbitMQ недоступен, повтор через {delay}с...", flush=True)
            await asyncio.sleep(delay)
    raise RuntimeError(f"RabbitMQ недоступен: {last!r}")


async def run_consumer(spec: ConsumerSpec) -> None:
    connection = await _connect_with_retry()
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)  # не берём больше 10 сообщений сразу
        await start_consumer(channel, spec)
        print(spec.ready_message or f"[{spec.name}] consumer запущен", flush=True)
        await asyncio.Future()  # бесконечное ожидание


def run(spec: ConsumerSpec) -> None:
    setup_logging()
    setup_sentry()
    setup_tracing(service_name=f"sirius-{spec.name}-worker")
    try:
        asyncio.run(run_consumer(spec))
    except KeyboardInterrupt:
        print(f"[{spec.name}] остановлен")
