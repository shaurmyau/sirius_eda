"""Инфраструктурный модуль RabbitMQ.

* единый topic-exchange `sirius_events` для всех событий проекта;
* топология очередей и Dead Letter Queue — в одном месте (`declare_topology`),
  её безопасно вызывать сколько угодно раз (declare идемпотентен);
* публикация событий: асинхронная (`publish_event`) и синхронная
  обёртка для обычных (sync) сервисов FastAPI (`publish_event_sync`).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import aio_pika
from aio_pika import DeliveryMode, ExchangeType

from app.core.config import settings
from app.core.correlation import get_correlation_id
from app.core.tracing import get_tracer

log = logging.getLogger("rabbitmq")

EXCHANGE_NAME = "sirius_events"
DLX_EXCHANGE_NAME = "dlx_exchange"


@dataclass(frozen=True)
class QueueDef:
    """Описание очереди consumer'а и её DLQ."""
    name: str
    routing_keys: tuple[str, ...]
    dlq_name: str
    dlq_routing_key: str


KITCHEN_QUEUE = QueueDef("kitchen_queue", ("order.paid",), "kitchen_dlq", "kitchen.dlq")
DELIVERY_QUEUE = QueueDef("delivery_queue", ("order.paid",), "delivery_dlq", "delivery.dlq")
# Saga: сервис заказов слушает провал доставки и компенсирует оплату.
ORDER_SAGA_QUEUE = QueueDef(
    "order_saga_queue", ("delivery.failed",), "order_saga_dlq", "order_saga.dlq"
)
LOYALTY_QUEUE = QueueDef(
    "loyalty_queue", ("order.paid", "order.cancelled"), "loyalty_dlq", "loyalty.dlq"
)
PROMO_QUEUE = QueueDef(
    "promo_queue", ("order.cancelled",), "promo_dlq", "promo.dlq"
)
ALL_QUEUES = (
    KITCHEN_QUEUE, DELIVERY_QUEUE, ORDER_SAGA_QUEUE, LOYALTY_QUEUE, PROMO_QUEUE,
)


async def get_connection(url: str | None = None) -> aio_pika.abc.AbstractRobustConnection:
    """Подключение к RabbitMQ. Robust — автоматически переподключается."""
    return await aio_pika.connect_robust(url or settings.RABBITMQ_URL, timeout=5)


async def declare_topology(channel):
    """Объявляет exchange'ы, очереди, DLQ и все bindings.

    Возвращает (exchange, {имя_очереди: queue}). Вызывается и publisher'ом, и
    consumer'ами, поэтому порядок запуска процессов не важен: событие,
    опубликованное до старта consumer'а, ляжет в уже существующую очередь.
    """
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, ExchangeType.TOPIC, durable=True
    )
    dlx = await channel.declare_exchange(
        DLX_EXCHANGE_NAME, ExchangeType.DIRECT, durable=True
    )
    queues = {}
    for qd in ALL_QUEUES:
        dlq = await channel.declare_queue(qd.dlq_name, durable=True)
        await dlq.bind(dlx, routing_key=qd.dlq_routing_key)

        queue = await channel.declare_queue(
            qd.name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE_NAME,
                "x-dead-letter-routing-key": qd.dlq_routing_key,
            },
        )
        for routing_key in qd.routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
        queues[qd.name] = queue
        queues[qd.dlq_name] = dlq
    return exchange, queues


def _build_message(payload: dict, headers: dict | None = None) -> aio_pika.Message:
    return aio_pika.Message(
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
        message_id=str(payload.get("event_id", "")) or None,
        headers=headers or {},
    )


async def publish_event(routing_key: str, payload: dict, *, exchange=None) -> None:
    """Публикует событие с correlation_id и W3C traceparent в AMQP headers."""
    tracer = get_tracer("sirius.rabbitmq")
    with tracer.start_as_current_span(f"rabbitmq.publish {routing_key}") as span:
        span.set_attribute("messaging.system", "rabbitmq")
        span.set_attribute("messaging.destination.name", routing_key)
        span.set_attribute("messaging.operation", "publish")
        if payload.get("order_id") is not None:
            span.set_attribute("order.id", str(payload["order_id"]))

        headers: dict = {}
        try:
            from opentelemetry.propagate import inject
            inject(headers)  # traceparent/baggage родительского span'а.
        except Exception:
            log.debug("OpenTelemetry context injection пропущен", exc_info=True)

        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id

        message = _build_message(payload, headers)
        if exchange is not None:
            await exchange.publish(message, routing_key=routing_key)
        else:
            connection = await get_connection()
            async with connection:
                channel = await connection.channel()
                exchange, _ = await declare_topology(channel)
                await exchange.publish(message, routing_key=routing_key)

    log.info("published %s event_id=%s", routing_key, payload.get("event_id"))

def publish_event_sync(routing_key: str, payload: dict, timeout: float = 10.0) -> None:
    """Синхронная обёртка для sync-сервисов (FastAPI вызывает их в threadpool,
    поэтому активного event loop в этом потоке нет)."""
    asyncio.run(asyncio.wait_for(publish_event(routing_key, payload), timeout))
