"""
Слой бизнес-логики модуля delivery (Круги 1 и 2).
Не зависит от fastapi и sqlalchemy.
"""
from app.exceptions import ForbiddenError, NotFoundError
from app.modules.delivery.repository import DeliveryRepository


class DeliveryService:
    """Бизнес-правила доставки заказов."""

    def __init__(self, repository: DeliveryRepository):
        # Внедрение зависимости через конструктор (инверсия зависимостей).
        self.repository = repository

    def assign_courier(self, order_id: int, courier_id: int) -> int:
        """Назначает курьера на заказ и возвращает id доставки."""
        order = self.repository.get_order_by_id(order_id)
        if not order:
            raise NotFoundError("Заказ не найден")

        # Бизнес-правило: курьера можно назначить только на оплаченный заказ.
        if order.status != "paid":
            raise ValueError("Курьера можно назначить только на оплаченный заказ")

        courier = self.repository.get_user_by_id(courier_id)
        if not courier:
            raise NotFoundError("Курьер не найден")
        if courier.is_blocked:
            raise ForbiddenError("Курьер заблокирован и не может быть назначен")

        # Бизнес-правило: один курьер - одна активная доставка.
        if self.repository.get_active_delivery_by_courier(courier_id):
            raise ValueError("У курьера уже есть активная доставка")

        return self.repository.save_delivery(order_id, courier_id).id

    def complete_delivery(self, delivery_id: int) -> None:
        """Завершает доставку и помечает заказ как доставленный."""
        delivery = self.repository.get_delivery_by_id(delivery_id)
        if not delivery:
            raise NotFoundError("Доставка не найдена")
        if delivery.status == "completed":
            raise ValueError("Доставка уже завершена")
        if delivery.status == "cancelled":
            raise ValueError("Отменённую доставку нельзя завершить")

        delivery.status = "completed"

        order = self.repository.get_order_by_id(delivery.order_id)
        if order:
            order.status = "delivered"

        self.repository.save_completion(delivery, order)
