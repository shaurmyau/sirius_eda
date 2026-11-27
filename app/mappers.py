"""ORM -> сущность."""
from app import entities, models


def to_user(row: models.User | None) -> entities.User | None:
    if row is None:
        return None
    role_name = row.role.name if row.role else "student"
    perms: set[str] = set()
    if row.role is not None:
        perms = {p.code for p in row.role.permissions}
    return entities.User(
        id=row.id,
        email=row.email,
        phone=row.phone,
        balance=row.balance,
        is_blocked=row.is_blocked,
        role=role_name,
        password_hash=row.password_hash,
        permissions=frozenset(perms),
    )


def to_menu_item(row):
    if row is None:
        return None
    return entities.MenuItem(
        id=row.id, name=row.name, price=row.price,
        is_available=row.is_available,
        category=getattr(row, "category", "food") or "food",
    )


def to_order(row):
    if row is None:
        return None
    return entities.Order(
        id=row.id, user_id=row.user_id, item_id=row.item_id,
        quantity=row.quantity, status=row.status,
        total_amount=getattr(row, "total_amount", None),
        discount_amount=getattr(row, "discount_amount", None) or 0,
        promo_code_id=getattr(row, "promo_code_id", None),
        points_spent=getattr(row, "points_spent", None) or 0,
    )


def to_delivery(row):
    if row is None:
        return None
    return entities.Delivery(id=row.id, order_id=row.order_id,
                             courier_id=row.courier_id, status=row.status)
