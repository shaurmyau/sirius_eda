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
        print(f"[Kitchen] Дубликат события {event_id} — пропускаем")
        return []

    # Бизнес-идемпотентность: один заказ — одна запись кухни.
    if db.query(models.KitchenOrder).filter_by(order_id=order_id).first():
        db.commit()
        print(f"[Kitchen] Заказ {order_id} уже на кухне — пропускаем")
        return []

    db.add(models.KitchenOrder(order_id=order_id, status="pending"))
    db.commit()
    print(f"[Kitchen] Принят заказ {order_id}")
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
        print(f"[Delivery] Дубликат события {event_id} — пропускаем")
        return []

    order = db.get(models.Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")  # poison → DLQ

    already = (db.query(models.Delivery)
               .filter(models.Delivery.order_id == order_id,
                       models.Delivery.status != "cancelled").first())
    if already:
        db.commit()
        print(f"[Delivery] Для заказа {order_id} доставка уже создана")
        return []

    courier_id = find_free_courier(db)
    base_payload = {
        "order_id": order_id,
        "customer_id": payload.get("customer_id", order.user_id),
        "amount": payload.get("amount", 0),
    }

    if courier_id is None:
        db.commit()  # фиксируем processed_event
        print(f"[Delivery] Нет свободного курьера для заказа {order_id} → DeliveryFailed")
        return [("delivery.failed", {
            "event_id": _derived_event_id("delivery.failed", event_id),
            "reason": "no_courier_available",
            **base_payload,
        })]

    db.add(models.Delivery(order_id=order_id, courier_id=courier_id, status="in_progress"))
    db.commit()
    print(f"[Delivery] Подготовка доставки для заказа {order_id}, курьер {courier_id}")
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
        print(f"[Saga] Дубликат события {event_id} — компенсация уже выполнена")
        return []

    order = db.get(models.Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")  # poison → DLQ

    if order.status not in ("paid", "processing"):
        db.commit()
        print(f"[Saga] Заказ {order_id} в статусе '{order.status}' — компенсация не нужна")
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

    print(f"[Saga] Заказ {order_id} отменён, клиенту {order.user_id} возвращено {amount:.2f}")
    return [("order.cancelled", {
        "event_id": _derived_event_id("order.cancelled", event_id),
        "order_id": order_id,
        "customer_id": order.user_id,
        "refunded": amount,
        "reason": payload.get("reason", "delivery_failed"),
    })]
