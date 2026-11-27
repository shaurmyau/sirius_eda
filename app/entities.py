"""Сущности предметной области (dataclass, без ORM)."""
from dataclasses import dataclass, field
from decimal import Decimal

from app.permissions import ROLE_PERMISSIONS


@dataclass
class User:
    id: int
    email: str
    phone: str | None
    balance: float
    is_blocked: bool
    role: str = "student"
    password_hash: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)

    def effective_permissions(self) -> frozenset[str]:
        """Гарантированно непустой набор прав.

        Если permissions не заполнены явно — берём из матрицы роли.
        Для admin возвращаем {"*"} — семантический wildcard.
        """
        if self.permissions:
            return self.permissions
        return frozenset(ROLE_PERMISSIONS.get(self.role, set()))

    def has_permission(self, code: str) -> bool:
        """Есть ли у пользователя право. Учитывает wildcard "*" (admin)."""
        perms = self.effective_permissions()
        return "*" in perms or code in perms


@dataclass
class MenuItem:
    id: int
    name: str
    price: float
    is_available: bool
    category: str = "food"


@dataclass
class Order:
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str
    total_amount: Decimal | None = None
    discount_amount: Decimal = Decimal("0.00")
    promo_code_id: int | None = None
    points_spent: Decimal = Decimal("0.00")


@dataclass
class Delivery:
    id: int
    order_id: int
    courier_id: int | None
    status: str
