"""Бизнес-логика consumer'ов на SQLite — без RabbitMQ и Docker."""
import pytest

from app import models
from app.workers import handlers as h
from tests.factories import (count, delivery_failed_event, order_paid_event,
                             order_status, seed_order, user_balance)


def _run(handler, session_factory, payload):
    db = session_factory()
    try:
        return handler(db, payload)
    finally:
        db.close()


# ------------------------------ Кухня ---------------------------------------
def test_kitchen_creates_order(session_factory):
    ids = seed_order(session_factory)
    _run(h.handle_order_paid_kitchen, session_factory, order_paid_event(ids))
    assert count(session_factory, models.KitchenOrder, order_id=ids["order_id"]) == 1


def test_kitchen_is_idempotent(session_factory):
    ids = seed_order(session_factory)
    event = order_paid_event(ids)
    for _ in range(3):
        _run(h.handle_order_paid_kitchen, session_factory, event)
    assert count(session_factory, models.KitchenOrder, order_id=ids["order_id"]) == 1
    assert count(session_factory, models.ProcessedEvent,
                 event_id=event["event_id"], consumer="kitchen") == 1


def test_kitchen_one_order_one_record_even_for_new_event_id(session_factory):
    ids = seed_order(session_factory)
    _run(h.handle_order_paid_kitchen, session_factory, order_paid_event(ids))
    _run(h.handle_order_paid_kitchen, session_factory, order_paid_event(ids))
    assert count(session_factory, models.KitchenOrder, order_id=ids["order_id"]) == 1


@pytest.mark.parametrize("bad", [{}, {"event_id": "e1"}, {"order_id": 1}])
def test_kitchen_rejects_malformed_payload(session_factory, bad):
    with pytest.raises(KeyError):
        _run(h.handle_order_paid_kitchen, session_factory, bad)


# ----------------------------- Доставка -------------------------------------
def test_delivery_assigns_free_courier(session_factory):
    ids = seed_order(session_factory, courier=True)
    out = _run(h.handle_order_paid_delivery, session_factory, order_paid_event(ids))
    assert [rk for rk, _ in out] == ["delivery.assigned"]
    assert count(session_factory, models.Delivery, order_id=ids["order_id"],
                 courier_id=ids["courier_id"], status="in_progress") == 1


def test_delivery_without_courier_emits_delivery_failed(session_factory):
    ids = seed_order(session_factory, courier=False)
    out = _run(h.handle_order_paid_delivery, session_factory, order_paid_event(ids))
    assert len(out) == 1
    routing_key, payload = out[0]
    assert routing_key == "delivery.failed"
    assert payload["order_id"] == ids["order_id"]
    assert payload["amount"] == ids["amount"]
    assert payload["reason"] == "no_courier_available"
    assert count(session_factory, models.Delivery, order_id=ids["order_id"]) == 0


def test_delivery_busy_courier_counts_as_unavailable(session_factory):
    first = seed_order(session_factory, courier=True)
    _run(h.handle_order_paid_delivery, session_factory, order_paid_event(first))
    second = seed_order(session_factory, courier=False)  # свободных курьеров больше нет
    out = _run(h.handle_order_paid_delivery, session_factory, order_paid_event(second))
    assert out[0][0] == "delivery.failed"


def test_delivery_is_idempotent(session_factory):
    ids = seed_order(session_factory, courier=True)
    event = order_paid_event(ids)
    _run(h.handle_order_paid_delivery, session_factory, event)
    again = _run(h.handle_order_paid_delivery, session_factory, event)
    assert again == []
    assert count(session_factory, models.Delivery, order_id=ids["order_id"]) == 1


def test_delivery_unknown_order_is_poison(session_factory):
    seed_order(session_factory)
    with pytest.raises(ValueError):
        _run(h.handle_order_paid_delivery, session_factory,
             {"event_id": "e", "order_id": 9999, "customer_id": 1, "amount": 1})


def test_failed_event_id_is_deterministic(session_factory):
    ids = seed_order(session_factory)
    event = order_paid_event(ids, event_id="same-event")
    first = _run(h.handle_order_paid_delivery, session_factory, event)[0][1]["event_id"]
    assert first == h._derived_event_id("delivery.failed", "same-event")


# ------------------------------- Saga ---------------------------------------
def test_saga_cancels_order_and_refunds(session_factory):
    ids = seed_order(session_factory, balance=10.0)
    out = _run(h.handle_delivery_failed, session_factory, delivery_failed_event(ids))
    assert order_status(session_factory, ids["order_id"]) == "cancelled"
    assert user_balance(session_factory, ids["user_id"]) == 10.0 + ids["amount"]
    assert [rk for rk, _ in out] == ["order.cancelled"]
    assert out[0][1]["refunded"] == ids["amount"]


def test_saga_compensation_is_idempotent(session_factory):
    ids = seed_order(session_factory, balance=0.0)
    event = delivery_failed_event(ids)
    _run(h.handle_delivery_failed, session_factory, event)
    again = _run(h.handle_delivery_failed, session_factory, event)
    assert again == []
    assert user_balance(session_factory, ids["user_id"]) == ids["amount"]  # не 2x


def test_saga_does_not_refund_twice_for_different_event_ids(session_factory):
    ids = seed_order(session_factory, balance=0.0)
    _run(h.handle_delivery_failed, session_factory, delivery_failed_event(ids))
    _run(h.handle_delivery_failed, session_factory, delivery_failed_event(ids))
    assert user_balance(session_factory, ids["user_id"]) == ids["amount"]


def test_saga_ignores_delivered_order(session_factory):
    ids = seed_order(session_factory, balance=5.0, status="delivered")
    out = _run(h.handle_delivery_failed, session_factory, delivery_failed_event(ids))
    assert out == []
    assert order_status(session_factory, ids["order_id"]) == "delivered"
    assert user_balance(session_factory, ids["user_id"]) == 5.0


# ----------------- Полная цепочка саги без брокера --------------------------
def test_saga_chain_order_paid_to_order_cancelled(session_factory):
    ids = seed_order(session_factory, balance=0.0, courier=False)
    out1 = _run(h.handle_order_paid_delivery, session_factory, order_paid_event(ids))
    assert out1[0][0] == "delivery.failed"
    out2 = _run(h.handle_delivery_failed, session_factory, out1[0][1])
    assert out2[0][0] == "order.cancelled"
    assert order_status(session_factory, ids["order_id"]) == "cancelled"
    assert user_balance(session_factory, ids["user_id"]) == ids["amount"]
