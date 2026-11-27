"""Инфраструктурный слой orders: транзакции, промокоды и списание баллов."""
from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.entities import MenuItem, Order, User
from app.mappers import to_menu_item, to_order, to_user
from app.memory_store import MemoryStore
from app.models import (
    LoyaltyAccount, LoyaltyTransaction, MenuItem as MenuItemModel,
    Order as OrderModel, PromoCode, PromoCodeUsage, User as UserModel,
)
from app.modules.promotions.policy import calculate_discount, validate_promo

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


class OrderRepository(ABC):
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None: ...
    @abstractmethod
    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None: ...
    @abstractmethod
    def save_order_and_update_balance(
        self, user_id: int, item_id: int, quantity: int,
        new_balance: float | None = None, promo_code: str | None = None
    ) -> int: ...
    @abstractmethod
    def spend_loyalty_points(self, order_id: int, user_id: int, points: Decimal) -> Decimal: ...
    @abstractmethod
    def get_order_by_id(self, order_id: int) -> Order | None: ...
    @abstractmethod
    def update_order_status(self, order_id: int, status: str) -> None: ...
    @abstractmethod
    def list_orders_by_user(self, user_id: int) -> list[Order]: ...


class SqlOrderRepository(OrderRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id):
        return to_user(self.db.query(UserModel).filter(UserModel.id == user_id).first())

    def get_menu_item_by_id(self, item_id):
        return to_menu_item(
            self.db.query(MenuItemModel).filter(MenuItemModel.id == item_id).first()
        )

    def save_order_and_update_balance(self, user_id, item_id, quantity, new_balance=None, promo_code=None):
        """Создаёт заказ и резервирует промокод в одной транзакции.

        SELECT FOR UPDATE не позволяет двум запросам одновременно потратить
        последний промокод или баланс одного клиента.
        """
        try:
            user = self.db.query(UserModel).filter(UserModel.id == user_id).with_for_update(of=UserModel).first()
            item = self.db.query(MenuItemModel).filter(MenuItemModel.id == item_id).first()
            if user is None or item is None:
                raise ValueError("Пользователь или блюдо не найдены")

            subtotal = money(item.price) * int(quantity)
            discount = Decimal("0.00")
            promo = None
            if promo_code:
                normalized = promo_code.strip().upper()
                promo = (
                    self.db.query(PromoCode)
                    .filter(PromoCode.code == normalized)
                    .with_for_update()
                    .first()
                )
                if promo is None:
                    raise ValueError("Промокод не найден")
                validate_promo(promo, subtotal)
                previous = (
                    self.db.query(PromoCodeUsage)
                    .filter(
                        PromoCodeUsage.promo_code_id == promo.id,
                        PromoCodeUsage.user_id == user_id,
                    )
                    .first()
                )
                if previous:
                    raise ValueError("Вы уже использовали этот промокод")
                discount = calculate_discount(promo, subtotal)

            final_total = max(subtotal - discount, Decimal("0.00")).quantize(CENT)
            available = money(user.balance)
            if available < final_total:
                raise ValueError("Недостаточно средств на балансе студента")

            user.balance = float(available - final_total)
            order = OrderModel(
                user_id=user_id,
                item_id=item_id,
                quantity=quantity,
                status="processing",
                total_amount=final_total,
                discount_amount=discount,
                promo_code_id=promo.id if promo else None,
                points_spent=Decimal("0.00"),
            )
            self.db.add(order)
            self.db.flush()
            if promo is not None:
                promo.current_uses += 1
                self.db.add(PromoCodeUsage(
                    promo_code_id=promo.id, user_id=user_id, order_id=order.id
                ))
            self.db.commit()
            self.db.refresh(order)
            return order.id
        except Exception:
            self.db.rollback()
            raise

    def spend_loyalty_points(self, order_id: int, user_id: int, points: Decimal) -> Decimal:
        requested = money(points)
        if requested <= 0:
            return Decimal("0.00")
        try:
            order = self.db.query(OrderModel).filter(OrderModel.id == order_id).with_for_update().first()
            account = (
                self.db.query(LoyaltyAccount)
                .filter(LoyaltyAccount.user_id == user_id)
                .with_for_update()
                .first()
            )
            user = self.db.query(UserModel).filter(UserModel.id == user_id).with_for_update(of=UserModel).first()
            if order is None or order.user_id != user_id:
                raise ValueError("Заказ не найден")
            if account is None:
                raise ValueError("Счёт лояльности ещё не создан")
            key = f"spend_order_{order_id}"
            existing = self.db.query(LoyaltyTransaction).filter_by(idempotency_key=key).first()
            if existing is not None:
                if abs(money(existing.amount)) != requested:
                    raise ValueError("Для заказа уже зафиксировано списание другого количества баллов")
                # Проверяем идемпотентность до 50%-го лимита: сумма заказа
                # уже уменьшена первым вызовом.
                order.status = "paid"
                self.db.commit()
                return requested

            total = money(order.total_amount)
            if total <= 0:
                raise ValueError("У заказа нет суммы к оплате")
            if requested > (total * Decimal("0.5")).quantize(CENT, rounding=ROUND_DOWN):
                raise ValueError("Баллами можно оплатить не более 50% заказа")
            if money(account.balance) < requested:
                raise ValueError("Недостаточно баллов лояльности")

            account.balance = money(account.balance) - requested
            # Заказ ранее резервировал всю сумму с внутреннего кошелька.
            # Возвращаем эквивалент потраченных баллов, чтобы итоговое списание
            # с денежного баланса было равно сумме после применения баллов.
            if user is not None:
                user.balance = float(money(user.balance) + requested)
            order.points_spent = money(order.points_spent) + requested
            order.total_amount = total - requested
            order.status = "paid"
            self.db.add(LoyaltyTransaction(
                account_id=account.id,
                amount=-requested,
                type="spend",
                order_id=order_id,
                idempotency_key=key,
            ))
            self.db.commit()
            return requested
        except Exception:
            self.db.rollback()
            raise

    def get_order_by_id(self, order_id):
        return to_order(self.db.query(OrderModel).filter(OrderModel.id == order_id).first())

    def update_order_status(self, order_id, status):
        row = self.db.query(OrderModel).filter(OrderModel.id == order_id).with_for_update().first()
        if row:
            row.status = status
            self.db.add(row)
            self.db.commit()

    def list_orders_by_user(self, user_id):
        rows = self.db.query(OrderModel).filter(OrderModel.user_id == user_id).all()
        return [to_order(r) for r in rows]


class InMemoryOrderRepository(OrderRepository):
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_user_by_id(self, user_id):
        return self.store.users.get(user_id)

    def get_menu_item_by_id(self, item_id):
        return self.store.menu_items.get(item_id)

    def save_order_and_update_balance(self, user_id, item_id, quantity, new_balance=None, promo_code=None):
        user = self.store.users[user_id]
        item = self.store.menu_items[item_id]
        subtotal = money(item.price) * int(quantity)
        discount = Decimal("0.00")
        promo_id = None
        if promo_code:
            normalized = promo_code.strip().upper()
            promo = self.store.promo_codes.get(normalized)
            if not promo:
                raise ValueError("Промокод не найден")
            if not promo.get("is_active", True):
                raise ValueError("Промокод неактивен")
            if promo.get("max_uses") is not None and promo.get("current_uses", 0) >= promo["max_uses"]:
                raise ValueError("Промокод исчерпан")
            if (normalized, user_id) in self.store.promo_usages:
                raise ValueError("Вы уже использовали этот промокод")
            if subtotal < money(promo.get("min_order_amount", 0)):
                raise ValueError("Сумма заказа меньше минимальной для промокода")
            typ = promo.get("discount_type", "percent")
            val = money(promo.get("discount_value", 0))
            discount = min(subtotal, (subtotal * val / 100).quantize(CENT) if typ == "percent" else val)
            promo_id = promo.get("id")
        final_total = max(subtotal - discount, Decimal("0.00"))
        balance = money(user.balance)
        if balance < final_total:
            raise ValueError("Недостаточно средств на балансе студента")
        user.balance = float(balance - final_total)
        order = Order(
            id=self.store.next_id(self.store.orders),
            user_id=user_id, item_id=item_id, quantity=quantity, status="processing",
            total_amount=final_total, discount_amount=discount, promo_code_id=promo_id,
        )
        self.store.orders[order.id] = order
        if promo_code:
            promo["current_uses"] = promo.get("current_uses", 0) + 1
            self.store.promo_usages.add((promo_code.strip().upper(), user_id))
        return order.id

    def spend_loyalty_points(self, order_id, user_id, points):
        requested = money(points)
        account = self.store.loyalty_accounts.get(user_id)
        order = self.store.orders.get(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("Заказ не найден")
        if not account:
            raise ValueError("Счёт лояльности ещё не создан")
        key = f"spend_order_{order_id}"
        if key in self.store.loyalty_transactions:
            existing = self.store.loyalty_transactions[key]
            if abs(money(existing["amount"])) != requested:
                raise ValueError("Для заказа уже зафиксировано списание другого количества баллов")
            order.status = "paid"
            return requested
        total = money(order.total_amount)
        if requested <= 0 or requested > (total * Decimal("0.5")).quantize(CENT, rounding=ROUND_DOWN):
            raise ValueError("Баллами можно оплатить не более 50% заказа")
        if money(account["balance"]) < requested:
            raise ValueError("Недостаточно баллов лояльности")
        account["balance"] = money(account["balance"]) - requested
        self.store.users[user_id].balance = float(money(self.store.users[user_id].balance) + requested)
        order.points_spent = money(order.points_spent) + requested
        order.total_amount = total - requested
        order.status = "paid"
        self.store.loyalty_transactions[key] = {"amount": -requested, "type": "spend", "order_id": order_id}
        return requested

    def get_order_by_id(self, order_id):
        return self.store.orders.get(order_id)

    def update_order_status(self, order_id, status):
        if order_id in self.store.orders:
            self.store.orders[order_id].status = status

    def list_orders_by_user(self, user_id):
        return [o for o in self.store.orders.values() if o.user_id == user_id]
