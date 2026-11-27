"""ORM-модели."""
from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        Numeric, String, Table)
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True)
    code = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

    permissions = relationship("Permission", secondary=role_permissions, lazy="selectin")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    is_blocked = Column(Boolean, default=False)
    password_hash = Column(String, nullable=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)
    role = relationship("Role", lazy="joined")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    jti = Column(String, unique=True, nullable=False)
    token_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)


class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True)
    category = Column(String(50), nullable=False, default="food", server_default="food")


class PromoCode(Base):
    __tablename__ = "promo_codes"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, unique=True)
    discount_type = Column(String(10), nullable=False)
    discount_value = Column(Numeric(12, 2), nullable=False)
    valid_from = Column(DateTime, nullable=False)
    valid_until = Column(DateTime, nullable=False)
    max_uses = Column(Integer, nullable=True)
    current_uses = Column(Integer, nullable=False, default=0, server_default="0")
    min_order_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    item_id = Column(Integer, ForeignKey("menu_items.id"))
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="processing")
    total_amount = Column(Numeric(12, 2), nullable=True)
    discount_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=True)
    points_spent = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    user = relationship("User")
    item = relationship("MenuItem")


class PromoCodeUsage(Base):
    __tablename__ = "promo_code_usages"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "user_id", name="uq_promo_code_user_usage"),
        UniqueConstraint("order_id", name="uq_promo_code_usage_order"),
    )
    id = Column(Integer, primary_key=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    used_at = Column(DateTime, server_default=func.now(), nullable=False)


class PromoCodeCompensation(Base):
    __tablename__ = "promo_code_compensations"
    id = Column(Integer, primary_key=True)
    compensation_key = Column(String(100), nullable=False, unique=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class LoyaltyAccount(Base):
    __tablename__ = "loyalty_accounts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    balance = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_earned = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    tier = Column(String(10), nullable=False, default="Bronze", server_default="Bronze")


class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    type = Column(String(10), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    idempotency_key = Column(String(120), nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Delivery(Base):
    __tablename__ = "deliveries"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    courier_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")
    order = relationship("Order")
    courier = relationship("User")


# ---------------------------------------------------------------------------
# Практическая работа № 7 — event-driven
# ---------------------------------------------------------------------------
class ProcessedEvent(Base):
    """Журнал обработанных событий: гарантия идемпотентности consumer'ов.

    Уникальность — по паре (event_id, consumer): одно и то же событие
    обрабатывается каждым consumer'ом (kitchen / delivery / order_saga)
    ровно один раз, но разные consumer'ы друг другу не мешают.
    """
    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint("event_id", "consumer", name="uq_processed_events_event_consumer"),
    )
    id = Column(Integer, primary_key=True)
    event_id = Column(String(64), nullable=False)
    consumer = Column(String(50), nullable=False)
    processed_at = Column(DateTime, server_default=func.now())


class KitchenOrder(Base):
    """Заказ в очереди кухни (создаётся consumer'ом по событию order.paid)."""
    __tablename__ = "kitchen_orders"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)
    status = Column(String(30), nullable=False, default="pending")
    created_at = Column(DateTime, server_default=func.now())
