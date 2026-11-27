"""Бизнес-логика consumer'ов (без RabbitMQ, только БД) — легко тестируется.

Каждый handler:
  1. «захватывает» event_id в таблице processed_events (идемпотентность);
  2. выполняет работу и коммитит всё одной транзакцией;
  3. возвращает список исходящих событий [(routing_key, payload), ...],
     которые каркас опубликует уже после успешного коммита.

Любое исключение (битый payload, нет заказа, ошибка БД) → сообщение
повторно доставляется один раз, затем уходит в DLQ (см. app/workers/base.py).
"""
from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP
import structlog

log = structlog.get_logger("workers.handlers")

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models

OutEvent = tuple[str, dict]

KITCHEN = "kitchen"
DELIVERY = "delivery"
ORDER_SAGA = "order_saga"


def _derived_event_id(kind: str, source_event_id: str) -> str:
    """Детерминированный id исходящего события: повторная обработка одного и
    того же входящего события даёт тот же id → downstream остаётся идемпотентным."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sirius:{kind}:{source_event_id}"))


def claim_event(db, event_id: str, consumer: str) -> bool:
    """True — событие обрабатываем впервые; False — это дубликат.

    Вставка в processed_events + UNIQUE(event_id, consumer) защищает и от
    гонки двух экземпляров consumer'а: проигравший получит IntegrityError.
    """
    exists = (db.query(models.ProcessedEvent)
              .filter_by(event_id=event_id, consumer=consumer).first())
    if exists:
        return False
    try:
        db.add(models.ProcessedEvent(event_id=event_id, consumer=consumer))
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


# ---------------------------------------------------------------------------
# Кухня
# ---------------------------------------------------------------------------
def handle_order_paid_kitchen(db, payload: dict) -> list[OutEvent]:
    event_id = str(payload["event_id"])
    order_id = int(payload["order_id"])

    if not claim_event(db, event_id, KITCHEN):
        log.info("duplicate_event_skipped", consumer=KITCHEN, event_id=event_id)
        return []

    # Бизнес-идемпотентность: один заказ — одна запись кухни.
    if db.query(models.KitchenOrder).filter_by(order_id=order_id).first():
        db.commit()
        log.info("order_already_in_kitchen", order_id=order_id)
        return []

    db.add(models.KitchenOrder(order_id=order_id, status="pending"))
    db.commit()
    log.info("kitchen_order_accepted", order_id=order_id)
    return []


# ---------------------------------------------------------------------------
# Доставка
# ---------------------------------------------------------------------------
def find_free_courier(db) -> int | None:
    """Первый незаблокированный курьер без активной доставки."""
    busy = select(models.Delivery.courier_id).where(
        models.Delivery.status == "in_progress",
        models.Delivery.courier_id.isnot(None),
    )
    row = (
        db.query(models.User.id)
        .join(models.Role, models.User.role_id == models.Role.id)
        .filter(
            models.Role.name == "courier",
            models.User.is_blocked.isnot(True),
            ~models.User.id.in_(busy),
        )
        .order_by(models.User.id)
        .first()
    )
    return row[0] if row else None


def handle_order_paid_delivery(db, payload: dict) -> list[OutEvent]:
    event_id = str(payload["event_id"])
    order_id = int(payload["order_id"])

    if not claim_event(db, event_id, DELIVERY):
        log.info("duplicate_event_skipped", consumer=DELIVERY, event_id=event_id)
        return []

    order = db.get(models.Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")  # poison → DLQ

    already = (db.query(models.Delivery)
               .filter(models.Delivery.order_id == order_id,
                       models.Delivery.status != "cancelled").first())
    if already:
        db.commit()
        log.info("delivery_already_created", order_id=order_id)
        return []

    courier_id = find_free_courier(db)
    base_payload = {
        "order_id": order_id,
        "customer_id": payload.get("customer_id", order.user_id),
        "amount": payload.get("amount", 0),
    }

    if courier_id is None:
        db.commit()  # фиксируем processed_event
        log.warning("delivery_failed_no_courier", order_id=order_id)
        return [("delivery.failed", {
            "event_id": _derived_event_id("delivery.failed", event_id),
            "reason": "no_courier_available",
            **base_payload,
        })]

    db.add(models.Delivery(order_id=order_id, courier_id=courier_id, status="in_progress"))
    order.status = "on_the_way"
    db.commit()
    from app.core.order_updates import publish_order_update
    publish_order_update(order_id, "on_the_way")
    log.info("delivery_prepared", order_id=order_id, courier_id=courier_id)
    return [("delivery.assigned", {
        "event_id": _derived_event_id("delivery.assigned", event_id),
        "courier_id": courier_id,
        **base_payload,
    })]


# ---------------------------------------------------------------------------
# Saga (хореография): компенсация оплаты при провале доставки
# ---------------------------------------------------------------------------
def handle_delivery_failed(db, payload: dict) -> list[OutEvent]:
    event_id = str(payload["event_id"])
    order_id = int(payload["order_id"])

    # compensation_key = (event_id, "order_saga"): повторная компенсация невозможна.
    if not claim_event(db, event_id, ORDER_SAGA):
        log.info("saga_duplicate_skipped", event_id=event_id)
        return []

    order = db.get(models.Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")  # poison → DLQ

    if order.status not in ("paid", "processing"):
        db.commit()
        log.info("saga_compensation_not_needed", order_id=order_id, status=order.status)
        return []

    amount = float(payload.get("amount") or 0)
    if amount <= 0:
        item = db.get(models.MenuItem, order.item_id)
        amount = float(item.price * order.quantity) if item else 0.0

    # Компенсирующие действия одной транзакцией.
    order.status = "cancelled"
    user = db.get(models.User, order.user_id)
    if user is not None:
        user.balance = float(user.balance or 0.0) + amount
    db.commit()
    from app.core.order_updates import publish_order_update
    publish_order_update(order_id, "cancelled")

    log.info("saga_order_cancelled_refund", order_id=order_id, user_id=order.user_id, refunded=amount)
    return [("order.cancelled", {
        "event_id": _derived_event_id("order.cancelled", event_id),
        "order_id": order_id,
        "customer_id": order.user_id,
        "refunded": amount,
        "reason": payload.get("reason", "delivery_failed"),
        "promo_code_id": order.promo_code_id,
        "discount_amount": str(order.discount_amount or 0),
        "points_spent": str(order.points_spent or 0),
    })]


# ---------------------------------------------------------------------------
# Трек A: программа лояльности и компенсации Saga
# ---------------------------------------------------------------------------
def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _tier_for(total_earned: Decimal) -> str:
    # Пороговые значения вынесены в одно место и описаны в ADR.
    if total_earned >= Decimal("2000.00"):
        return "Gold"
    if total_earned >= Decimal("500.00"):
        return "Silver"
    return "Bronze"


def handle_order_paid_loyalty(db, payload: dict) -> list[OutEvent]:
    event_id = str(payload["event_id"])
    order_id = int(payload["order_id"])
    if not claim_event(db, event_id, "loyalty"):
        return []

    order = db.get(models.Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")
    if order.status not in ("paid", "on_the_way", "delivered"):
        db.commit()
        return []

    account = (
        db.query(models.LoyaltyAccount)
        .filter_by(user_id=order.user_id)
        .with_for_update()
        .first()
    )
    if account is None:
        account = models.LoyaltyAccount(
            user_id=order.user_id, balance=Decimal("0.00"),
            total_earned=Decimal("0.00"), tier="Bronze",
        )
        db.add(account)
        db.flush()

    key = f"earn_order_{order_id}"
    exists = db.query(models.LoyaltyTransaction).filter_by(idempotency_key=key).first()
    if exists:
        db.commit()
        return []

    amount = _money(payload.get("total", payload.get("amount", order.total_amount or 0)))
    percentages = {"Bronze": Decimal("3"), "Silver": Decimal("5"), "Gold": Decimal("7")}
    percentage = percentages.get(account.tier, Decimal("3"))
    earned = (amount * percentage / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if earned <= 0:
        db.commit()
        return []

    account.balance = _money(account.balance) + earned
    account.total_earned = _money(account.total_earned) + earned
    account.tier = _tier_for(account.total_earned)
    db.add(models.LoyaltyTransaction(
        account_id=account.id, amount=earned, type="earn", order_id=order_id,
        idempotency_key=key,
    ))
    db.commit()
    log.info("loyalty_points_earned", order_id=order_id, user_id=order.user_id, amount=str(earned), tier=account.tier)
    return []


def handle_order_cancelled_loyalty(db, payload: dict) -> list[OutEvent]:
    event_id = str(payload["event_id"])
    order_id = int(payload["order_id"])
    if not claim_event(db, event_id, "loyalty"):
        return []

    order = db.get(models.Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")
    account = (
        db.query(models.LoyaltyAccount)
        .filter_by(user_id=order.user_id)
        .with_for_update()
        .first()
    )
    if account is None:
        db.commit()
        return []

    spend = db.query(models.LoyaltyTransaction).filter_by(
        idempotency_key=f"spend_order_{order_id}"
    ).first()
    refund_key = f"refund_order_{order_id}"
    if spend is not None and db.query(models.LoyaltyTransaction).filter_by(idempotency_key=refund_key).first() is None:
        refund = abs(_money(spend.amount))
        account.balance = _money(account.balance) + refund
        db.add(models.LoyaltyTransaction(
            account_id=account.id, amount=refund, type="refund", order_id=order_id,
            idempotency_key=refund_key,
        ))

    earned = db.query(models.LoyaltyTransaction).filter_by(
        idempotency_key=f"earn_order_{order_id}"
    ).first()
    revoke_key = f"revoke_earn_order_{order_id}"
    if earned is not None and db.query(models.LoyaltyTransaction).filter_by(idempotency_key=revoke_key).first() is None:
        revoke = abs(_money(earned.amount))
        account.balance = max(_money(account.balance) - revoke, Decimal("0.00"))
        account.total_earned = max(_money(account.total_earned) - revoke, Decimal("0.00"))
        db.add(models.LoyaltyTransaction(
            account_id=account.id, amount=-revoke, type="revoke", order_id=order_id,
            idempotency_key=revoke_key,
        ))

    account.tier = _tier_for(_money(account.total_earned))
    db.commit()
    log.info("loyalty_order_compensated", order_id=order_id, user_id=order.user_id)
    return []


# ---------------------------------------------------------------------------
# Трек A: восстановление использования промокода по OrderCancelled
# ---------------------------------------------------------------------------
def handle_order_cancelled_promo(db, payload: dict) -> list[OutEvent]:
    event_id = str(payload["event_id"])
    order_id = int(payload["order_id"])
    if not claim_event(db, event_id, "promo"):
        return []

    usage = (
        db.query(models.PromoCodeUsage)
        .filter_by(order_id=order_id)
        .with_for_update()
        .first()
    )
    key = f"restore_promo_order_{order_id}"
    already = db.query(models.PromoCodeCompensation).filter_by(compensation_key=key).first()
    if usage is not None and already is None:
        promo = (
            db.query(models.PromoCode)
            .filter_by(id=usage.promo_code_id)
            .with_for_update()
            .first()
        )
        if promo is not None:
            promo.current_uses = max(0, int(promo.current_uses or 0) - 1)
            db.add(models.PromoCodeCompensation(
                compensation_key=key, promo_code_id=promo.id, order_id=order_id,
            ))
        db.delete(usage)
    db.commit()
    log.info("promo_usage_compensated", order_id=order_id, restored=usage is not None and already is None)
    return []]
