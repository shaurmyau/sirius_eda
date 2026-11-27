"""Регрессионные тесты учебных треков A и B (SQLite / in-memory)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import models
from app.core.jwt import create_access_token
from app.entities import Order, User
from app.main import app
from app.memory_store import memory_store
from app.modules.orders.repository import SqlOrderRepository
from app.modules.promotions.policy import calculate_discount, validate_promo
from app.workers.handlers import (
    handle_order_cancelled_loyalty,
    handle_order_cancelled_promo,
    handle_order_paid_loyalty,
)
from tests.factories import seed_order


def _run(handler, session_factory, payload):
    db = session_factory()
    try:
        return handler(db, payload)
    finally:
        db.close()


def test_promo_is_applied_atomically_and_once_per_customer(session_factory):
    ids = seed_order(session_factory, balance=100.0, price=50.0, quantity=2)
    db = session_factory()
    try:
        promo = models.PromoCode(
            code="WELCOME10", discount_type="percent", discount_value=10,
            valid_from=datetime.utcnow() - timedelta(days=1),
            valid_until=datetime.utcnow() + timedelta(days=1),
            max_uses=1, current_uses=0, min_order_amount=Decimal("50.00"),
            is_active=True,
        )
        db.add(promo)
        db.commit()
    finally:
        db.close()

    repo = SqlOrderRepository(session_factory())
    try:
        order_id = repo.save_order_and_update_balance(
            ids["user_id"], ids["item_id"], 2, None, "welcome10"
        )
        with pytest.raises(ValueError, match="исчерпан|использовали"):
            # Лимит max_uses=1 запрещает повторное применение.
            repo.save_order_and_update_balance(
                ids["user_id"], ids["item_id"], 1, None, "WELCOME10"
            )
    finally:
        repo.db.close()

    db = session_factory()
    try:
        order = db.get(models.Order, order_id)
        promo = db.query(models.PromoCode).filter_by(code="WELCOME10").one()
        usage = db.query(models.PromoCodeUsage).filter_by(order_id=order_id).one()
        assert order.total_amount == Decimal("90.00")
        assert order.discount_amount == Decimal("10.00")
        assert promo.current_uses == 1
        assert usage.user_id == ids["user_id"]
    finally:
        db.close()


def test_expired_and_inactive_promo_codes_are_rejected():
    class Promo:
        is_active = True
        valid_from = datetime.utcnow() - timedelta(days=2)
        valid_until = datetime.utcnow() - timedelta(days=1)
        max_uses = 10
        current_uses = 0
        min_order_amount = Decimal("0")

    with pytest.raises(ValueError, match="истёк"):
        validate_promo(Promo(), Decimal("10.00"))
    Promo.valid_until = datetime.utcnow() + timedelta(days=1)
    Promo.is_active = False
    with pytest.raises(ValueError, match="неактивен"):
        validate_promo(Promo(), Decimal("10.00"))


def test_fixed_and_percent_discounts_are_bounded_by_subtotal():
    class Promo:
        discount_type = "fixed"
        discount_value = Decimal("120.00")

    assert calculate_discount(Promo(), Decimal("100.00")) == Decimal("100.00")
    Promo.discount_type = "percent"
    Promo.discount_value = Decimal("15")
    assert calculate_discount(Promo(), Decimal("100.00")) == Decimal("15.00")


def test_loyalty_earn_is_idempotent_by_order_key(session_factory):
    ids = seed_order(session_factory, status="paid", balance=0.0, price=100.0, quantity=1)
    payload = {"event_id": "paid-event-a", "order_id": ids["order_id"], "total": 100.0}
    _run(handle_order_paid_loyalty, session_factory, payload)
    # Иной event_id для того же заказа также не создаёт второе начисление.
    _run(handle_order_paid_loyalty, session_factory, {**payload, "event_id": "paid-event-b"})

    db = session_factory()
    try:
        account = db.query(models.LoyaltyAccount).filter_by(user_id=ids["user_id"]).one()
        ledger = db.query(models.LoyaltyTransaction).filter_by(
            idempotency_key=f"earn_order_{ids['order_id']}"
        ).all()
        assert account.balance == Decimal("3.00")
        assert account.total_earned == Decimal("3.00")
        assert account.tier == "Bronze"
        assert len(ledger) == 1
        assert ledger[0].type == "earn"
    finally:
        db.close()


def test_loyalty_cancel_refunds_spent_points_and_revokes_earned(session_factory):
    ids = seed_order(session_factory, status="cancelled")
    db = session_factory()
    try:
        account = models.LoyaltyAccount(
            user_id=ids["user_id"], balance=Decimal("20.00"),
            total_earned=Decimal("3.00"), tier="Bronze",
        )
        db.add(account)
        db.flush()
        db.add_all([
            models.LoyaltyTransaction(
                account_id=account.id, amount=Decimal("-10.00"), type="spend",
                order_id=ids["order_id"], idempotency_key=f"spend_order_{ids['order_id']}",
            ),
            models.LoyaltyTransaction(
                account_id=account.id, amount=Decimal("3.00"), type="earn",
                order_id=ids["order_id"], idempotency_key=f"earn_order_{ids['order_id']}",
            ),
        ])
        db.commit()
    finally:
        db.close()

    payload = {"event_id": "cancel-loyalty-a", "order_id": ids["order_id"]}
    _run(handle_order_cancelled_loyalty, session_factory, payload)
    _run(handle_order_cancelled_loyalty, session_factory, {**payload, "event_id": "cancel-loyalty-b"})

    db = session_factory()
    try:
        account = db.query(models.LoyaltyAccount).filter_by(user_id=ids["user_id"]).one()
        assert account.balance == Decimal("27.00")
        assert account.total_earned == Decimal("0.00")
        assert db.query(models.LoyaltyTransaction).filter_by(
            idempotency_key=f"refund_order_{ids['order_id']}"
        ).count() == 1
        assert db.query(models.LoyaltyTransaction).filter_by(
            idempotency_key=f"revoke_earn_order_{ids['order_id']}"
        ).count() == 1
    finally:
        db.close()


def test_promo_compensation_restores_usage_once(session_factory):
    ids = seed_order(session_factory)
    db = session_factory()
    try:
        promo = models.PromoCode(
            code="RESTORE", discount_type="fixed", discount_value=Decimal("5"),
            valid_from=datetime.utcnow() - timedelta(days=1),
            valid_until=datetime.utcnow() + timedelta(days=1),
            max_uses=5, current_uses=1, min_order_amount=0, is_active=True,
        )
        db.add(promo)
        db.flush()
        db.add(models.PromoCodeUsage(
            promo_code_id=promo.id, user_id=ids["user_id"], order_id=ids["order_id"]
        ))
        db.commit()
    finally:
        db.close()

    payload = {"event_id": "cancel-promo-a", "order_id": ids["order_id"]}
    _run(handle_order_cancelled_promo, session_factory, payload)
    _run(handle_order_cancelled_promo, session_factory, {**payload, "event_id": "cancel-promo-b"})

    db = session_factory()
    try:
        promo = db.query(models.PromoCode).filter_by(code="RESTORE").one()
        assert promo.current_uses == 0
        assert db.query(models.PromoCodeUsage).filter_by(order_id=ids["order_id"]).count() == 0
        assert db.query(models.PromoCodeCompensation).filter_by(
            compensation_key=f"restore_promo_order_{ids['order_id']}"
        ).count() == 1
    finally:
        db.close()


def test_spending_loyalty_points_is_capped_at_half_and_ledgered(session_factory):
    ids = seed_order(session_factory, balance=0.0, price=50.0, quantity=2)
    db = session_factory()
    try:
        order = db.get(models.Order, ids["order_id"])
        order.total_amount = Decimal("100.01")
        account = models.LoyaltyAccount(
            user_id=ids["user_id"], balance=Decimal("100.00"),
            total_earned=Decimal("100.00"), tier="Bronze",
        )
        db.add(account)
        db.commit()
    finally:
        db.close()

    repo = SqlOrderRepository(session_factory())
    try:
        with pytest.raises(ValueError, match="50%"):
            repo.spend_loyalty_points(ids["order_id"], ids["user_id"], Decimal("50.01"))
        repo.spend_loyalty_points(ids["order_id"], ids["user_id"], Decimal("40"))
        # Повтор того же запроса не списывает баллы повторно.
        repo.spend_loyalty_points(ids["order_id"], ids["user_id"], Decimal("40"))
    finally:
        repo.db.close()

    db = session_factory()
    try:
        order = db.get(models.Order, ids["order_id"])
        user = db.get(models.User, ids["user_id"])
        account = db.query(models.LoyaltyAccount).filter_by(user_id=ids["user_id"]).one()
        assert order.total_amount == Decimal("60.01")
        assert order.points_spent == Decimal("40.00")
        assert account.balance == Decimal("60.00")
        assert user.balance == 40.0
    finally:
        db.close()


def test_websocket_sends_snapshot_to_order_owner():
    memory_store.clear()
    memory_store.users[1] = User(1, "owner@example.test", None, 0.0, False, "student")
    memory_store.users[2] = User(2, "other@example.test", None, 0.0, False, "student")
    memory_store.orders[1] = Order(1, 1, 1, 1, "paid")
    owner_token = create_access_token(1)
    other_token = create_access_token(2)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/orders/1?token={owner_token}") as websocket:
            assert websocket.receive_json() == {
                "type": "snapshot", "order_id": 1, "status": "preparing"
            }
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/orders/1?token={other_token}") as websocket:
                websocket.receive_json()
    memory_store.clear()



def test_legacy_order_can_spend_points_without_persisted_total(session_factory):
    ids = seed_order(session_factory, status="processing", balance=100.0, price=50.0, quantity=2)
    db = session_factory()
    try:
        order = db.get(models.Order, ids["order_id"])
        order.total_amount = None
        account = models.LoyaltyAccount(
            user_id=ids["user_id"], balance=Decimal("100.00"),
            total_earned=Decimal("100.00"), tier="Bronze",
        )
        db.add(account)
        db.commit()
    finally:
        db.close()

    repo = SqlOrderRepository(session_factory())
    try:
        repo.spend_loyalty_points(ids["order_id"], ids["user_id"], Decimal("40.00"))
    finally:
        repo.db.close()

    db = session_factory()
    try:
        order = db.get(models.Order, ids["order_id"])
        assert order.total_amount == Decimal("60.00")
        assert order.points_spent == Decimal("40.00")
    finally:
        db.close()


def test_cancelling_order_also_releases_assigned_courier(session_factory):
    ids = seed_order(session_factory, status="on_the_way", courier=True)
    db = session_factory()
    try:
        db.add(models.Delivery(
            order_id=ids["order_id"], courier_id=ids["courier_id"], status="in_progress"
        ))
        db.commit()
    finally:
        db.close()

    repo = SqlOrderRepository(session_factory())
    try:
        repo.update_order_status(ids["order_id"], "cancelled")
    finally:
        repo.db.close()

    db = session_factory()
    try:
        delivery = db.query(models.Delivery).filter_by(order_id=ids["order_id"]).one()
        assert delivery.status == "cancelled"
    finally:
        db.close()
