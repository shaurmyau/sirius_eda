"""Интеграционные тесты consumer'ов на реальном RabbitMQ (вариант «В», 10 баллов).

Проверяют:
  1. consumer обрабатывает корректное сообщение;
  2. consumer идемпотентен (повторная доставка не создаёт дубль);
  3. «битое» сообщение не ломает очередь — уходит в DLQ;
  + кухня и доставка получают одно событие независимо (fan-out);
  + Saga: DeliveryFailed → отмена заказа, возврат денег, OrderCancelled.
"""
import asyncio
import json
import uuid

import pytest

aio_pika = pytest.importorskip("aio_pika")

from app import models  # noqa: E402
from app.core.rabbitmq import publish_event  # noqa: E402
from app.workers.kitchen_consumer import SPEC as KITCHEN_SPEC  # noqa: E402
from app.workers.order_saga_consumer import SPEC as SAGA_SPEC  # noqa: E402
from delivery_worker import SPEC as DELIVERY_SPEC  # noqa: E402
from tests.factories import (count, delivery_failed_event, order_paid_event,  # noqa: E402
                             order_status, seed_order, user_balance)
from tests.integration.conftest import PROBE_QUEUE  # noqa: E402
from tests.integration.helpers import get_message, running_consumers, wait_until  # noqa: E402

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------- 1. happy path
def test_consumer_processes_valid_message(broker, session_factory):
    ids = seed_order(session_factory)

    async def scenario():
        async with running_consumers(broker, [KITCHEN_SPEC], session_factory) as env:
            await publish_event("order.paid", order_paid_event(ids), exchange=env.exchange)
            assert await wait_until(
                lambda: count(session_factory, models.KitchenOrder, order_id=ids["order_id"]) == 1
            ), "кухня не приняла заказ"

    asyncio.run(scenario())


def test_kitchen_and_delivery_receive_event_independently(broker, session_factory):
    ids = seed_order(session_factory, courier=True)

    async def scenario():
        async with running_consumers(broker, [KITCHEN_SPEC, DELIVERY_SPEC], session_factory) as env:
            await publish_event("order.paid", order_paid_event(ids), exchange=env.exchange)
            assert await wait_until(
                lambda: count(session_factory, models.KitchenOrder, order_id=ids["order_id"]) == 1
                and count(session_factory, models.Delivery, order_id=ids["order_id"],
                          courier_id=ids["courier_id"]) == 1
            ), "событие должно дойти и до кухни, и до доставки"

    asyncio.run(scenario())


# ---------------------------------------------------------------- 2. idempotency
def test_consumer_is_idempotent_on_redelivery(broker, session_factory):
    first = seed_order(session_factory)
    sentinel = seed_order(session_factory)
    event = order_paid_event(first)

    async def scenario():
        async with running_consumers(broker, [KITCHEN_SPEC], session_factory) as env:
            # Одно и то же событие (тот же event_id) приходит трижды.
            for _ in range(3):
                await publish_event("order.paid", event, exchange=env.exchange)
            # Сентинел: когда он обработан, все дубликаты гарантированно разобраны.
            await publish_event("order.paid", order_paid_event(sentinel), exchange=env.exchange)
            assert await wait_until(
                lambda: count(session_factory, models.KitchenOrder,
                              order_id=sentinel["order_id"]) == 1
            )

    asyncio.run(scenario())
    assert count(session_factory, models.KitchenOrder, order_id=first["order_id"]) == 1
    assert count(session_factory, models.ProcessedEvent,
                 event_id=event["event_id"], consumer="kitchen") == 1


# ---------------------------------------------------------------- 3. DLQ
def test_poison_message_goes_to_dlq_and_queue_keeps_working(broker, session_factory):
    ids = seed_order(session_factory)

    async def scenario():
        async with running_consumers(broker, [KITCHEN_SPEC], session_factory) as env:
            await env.exchange.publish(aio_pika.Message(body=b"not-json"),
                                       routing_key="order.paid")

            dead = await get_message(env.queues["kitchen_dlq"])
            assert dead is not None, "битое сообщение должно попасть в kitchen_dlq"
            assert dead.body == b"not-json"
            assert dead.headers.get("x-death"), "RabbitMQ должен проставить x-death"

            # Очередь не заблокирована: следующее нормальное сообщение обрабатывается.
            await publish_event("order.paid", order_paid_event(ids), exchange=env.exchange)
            assert await wait_until(
                lambda: count(session_factory, models.KitchenOrder, order_id=ids["order_id"]) == 1
            ), "после poison-сообщения очередь должна продолжать работать"

    asyncio.run(scenario())


def test_message_with_missing_fields_goes_to_dlq(broker, session_factory):
    async def scenario():
        async with running_consumers(broker, [KITCHEN_SPEC], session_factory) as env:
            await publish_event("order.paid", {"order_id": 1}, exchange=env.exchange)  # нет event_id
            dead = await get_message(env.queues["kitchen_dlq"])
            assert dead is not None
            assert json.loads(dead.body) == {"order_id": 1}

    asyncio.run(scenario())


# ---------------------------------------------------------------- Saga
def test_saga_compensates_when_no_courier(broker, session_factory):
    ids = seed_order(session_factory, balance=10.0, price=30.0, quantity=2, courier=False)

    async def scenario():
        async with running_consumers(broker, [DELIVERY_SPEC, SAGA_SPEC], session_factory) as env:
            probe = await env.channel.declare_queue(PROBE_QUEUE, auto_delete=True)
            await probe.bind(env.exchange, routing_key="order.cancelled")

            await publish_event("order.paid", order_paid_event(ids), exchange=env.exchange)

            assert await wait_until(
                lambda: order_status(session_factory, ids["order_id"]) == "cancelled"
            ), "заказ должен быть отменён компенсацией"
            cancelled = await get_message(probe)
            assert cancelled is not None, "должно быть опубликовано order.cancelled"
            body = json.loads(cancelled.body)
            assert body["order_id"] == ids["order_id"]
            assert body["refunded"] == ids["amount"]

    asyncio.run(scenario())
    assert user_balance(session_factory, ids["user_id"]) == 10.0 + ids["amount"]


def test_saga_compensation_is_idempotent(broker, session_factory):
    first = seed_order(session_factory, balance=0.0)
    sentinel = seed_order(session_factory, balance=0.0)
    event = delivery_failed_event(first, event_id=f"dup-{uuid.uuid4()}")

    async def scenario():
        async with running_consumers(broker, [SAGA_SPEC], session_factory) as env:
            await publish_event("delivery.failed", event, exchange=env.exchange)
            await publish_event("delivery.failed", event, exchange=env.exchange)
            await publish_event("delivery.failed", delivery_failed_event(sentinel),
                                exchange=env.exchange)
            assert await wait_until(
                lambda: order_status(session_factory, sentinel["order_id"]) == "cancelled"
            )

    asyncio.run(scenario())
    assert order_status(session_factory, first["order_id"]) == "cancelled"
    assert user_balance(session_factory, first["user_id"]) == first["amount"]  # вернули один раз
