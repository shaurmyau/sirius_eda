"""Бизнес-логика orders. IDOR-проверка в сервисе."""
from app.entities import User
from app.exceptions import ForbiddenError, NotFoundError
from app.modules.orders.repository import OrderRepository

CANCELLABLE = ("processing", "paid")


class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(self, user_id, item_id, quantity) -> int:
        u = self.repository.get_user_by_id(user_id)
        if not u: raise NotFoundError("Пользователь не найден")
        it = self.repository.get_menu_item_by_id(item_id)
        if not it: raise NotFoundError("Блюдо не найдено")
        if not it.is_available: raise ValueError("Блюдо недоступно")
        total = it.price * quantity
        if u.balance < total: raise ValueError("Недостаточно средств на балансе студента")
        return self.repository.save_order_and_update_balance(user_id, item_id, quantity, u.balance - total)

    def cancel_order(self, order_id: int, current_user: User) -> None:
        o = self.repository.get_order_by_id(order_id)
        if not o: raise NotFoundError("Заказ не найден")
        if o.user_id != current_user.id and current_user.role != "admin":
            raise ForbiddenError("Нельзя отменить чужой заказ")
        if o.status not in CANCELLABLE:
            raise ValueError("Заказ нельзя отменить в текущем статусе")
        self.repository.update_order_status(order_id, "cancelled")
