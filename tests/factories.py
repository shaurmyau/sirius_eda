"""Помощники для тестов consumer'ов: наполнение БД и чтение состояния."""
import uuid

from app import models


def _role(db, name: str):
    role = db.query(models.Role).filter_by(name=name).first()
    if role is None:
        role = models.Role(name=name, description=f"Роль {name}")
        db.add(role)
        db.flush()
    return role


def seed_order(session_factory, *, balance=10.0, price=30.0, quantity=2,
               status="paid", courier=False) -> dict:
    """Создаёт студента, блюдо, заказ (и, по желанию, курьера)."""
    db = session_factory()
    try:
        student_role = _role(db, "student")
        user = models.User(email=f"{uuid.uuid4().hex[:8]}@sirius.ru", balance=balance,
                           is_blocked=False, role_id=student_role.id)
        item = models.MenuItem(name=f"item-{uuid.uuid4().hex[:6]}", price=price,
                               is_available=True, category="food")
        db.add_all([user, item])
        db.flush()
        order = models.Order(user_id=user.id, item_id=item.id, quantity=quantity, status=status)
        db.add(order)
        db.flush()
        courier_id = None
        if courier:
            courier_role = _role(db, "courier")
            c = models.User(email=f"{uuid.uuid4().hex[:8]}@courier.ru", balance=0.0,
                            is_blocked=False, role_id=courier_role.id)
            db.add(c)
            db.flush()
            courier_id = c.id
        ids = {"user_id": user.id, "order_id": order.id, "item_id": item.id,
               "courier_id": courier_id, "amount": float(price * quantity)}
        db.commit()
        return ids
    finally:
        db.close()


def order_paid_event(ids: dict, event_id: str | None = None) -> dict:
    return {"event_id": event_id or str(uuid.uuid4()), "order_id": ids["order_id"],
            "customer_id": ids["user_id"], "amount": ids["amount"]}


def delivery_failed_event(ids: dict, event_id: str | None = None) -> dict:
    return {"event_id": event_id or str(uuid.uuid4()), "order_id": ids["order_id"],
            "customer_id": ids["user_id"], "amount": ids["amount"],
            "reason": "no_courier_available"}


def count(session_factory, model, **filters) -> int:
    db = session_factory()
    try:
        return db.query(model).filter_by(**filters).count()
    finally:
        db.close()


def order_status(session_factory, order_id: int) -> str | None:
    db = session_factory()
    try:
        row = db.get(models.Order, order_id)
        return row.status if row else None
    finally:
        db.close()


def user_balance(session_factory, user_id: int) -> float:
    db = session_factory()
    try:
        return float(db.get(models.User, user_id).balance)
    finally:
        db.close()
