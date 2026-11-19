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

log = logging.getLogger("workers")

Handler = Callable[[object, dict], list[OutEvent]]


@dataclass(frozen=True)
class ConsumerSpec:
    name: str
    queue: QueueDef
    handler: Handler
    ready_message: str = ""


def make_processor(spec: ConsumerSpec, session_factory, exchange):
    async def on_message(message) -> None:
        try:
            async with message.process(requeue=True, reject_on_redelivered=True):
                payload = json.loads(message.body)
                if not isinstance(payload, dict):
                    raise ValueError("payload должен быть JSON-объектом")
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
        except Exception as exc:  # сообщение уже nack'нуто / отправлено в DLQ
            log.warning("[%s] ошибка обработки (redelivered=%s): %r",
                        spec.name, message.redelivered, exc)
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
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run_consumer(spec))
    except KeyboardInterrupt:
        print(f"[{spec.name}] остановлен")
