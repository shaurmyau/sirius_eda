"""
Слой бизнес-логики модуля orders (Круги 1 и 2).
Не зависит от fastapi и sqlalchemy.
"""
from app.exceptions import NotFoundError
from app.modules.orders.repository import OrderRepository


class OrderService:
    """Бизнес-правила обработки заказов."""

    def __init__(self, repository: OrderRepository):
        # Внедрение зависимости через конструктор (инверсия зависимостей).
        self.repository = repository

    def create_order(self, user_id: int, item_id: int, quantity: int) -> int:
        """
        Сценарий оформления заказа. Возвращает идентификатор заказа.
        Возбуждает ValueError (или его наследников) при нарушении бизнес-правил.
        """
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")
        if not item.is_available:
            raise ValueError("Блюдо недоступно")

        total_cost = item.price * quantity
        if user.balance < total_cost:
            raise ValueError("Недостаточно средств на балансе студента")

        new_balance = user.balance - total_cost
        return self.repository.save_order_and_update_balance(
            user_id, item_id, quantity, new_balance
        )
