"""Слой бизнес-логики delivery. IDOR-проверки в сервисе."""
from app.entities import User
from app.exceptions import ForbiddenError, NotFoundError
from app.modules.delivery.repository import DeliveryRepository


class DeliveryService:
    def __init__(self, repository: DeliveryRepository):
        self.repository = repository

    def assign_courier(self, order_id, courier_id) -> int:
        o = self.repository.get_order_by_id(order_id)
        if not o:
            raise NotFoundError("Заказ не найден")
        if o.status != "paid":
            raise ValueError("Курьера можно назначить только на оплаченный заказ")
        c = self.repository.get_user_by_id(courier_id)
        if not c:
            raise NotFoundError("Курьер не найден")
        if c.is_blocked:
            raise ForbiddenError("Курьер заблокирован")
        if self.repository.get_active_delivery_by_courier(courier_id):
            raise ValueError("У курьера уже есть активная доставка")
        delivery_id = self.repository.save_delivery(order_id, courier_id).id
        from app.core.order_updates import publish_order_update
        publish_order_update(order_id, "on_the_way")
        return delivery_id

    def complete_delivery(self, delivery_id, current_user: User) -> None:
        d = self.repository.get_delivery_by_id(delivery_id)
        if not d:
            raise NotFoundError("Доставка не найдена")
        if current_user.role == "courier" and d.courier_id != current_user.id:
            raise ForbiddenError("Курьер может завершить только свою доставку")
        if current_user.role not in ("courier", "admin"):
            raise ForbiddenError("Завершить доставку может только курьер или админ")
        if d.status == "completed":
            raise ValueError("Доставка уже завершена")
        if d.status == "cancelled":
            raise ValueError("Отменённую доставку нельзя завершить")
        d.status = "completed"
        o = self.repository.get_order_by_id(d.order_id)
        if o:
            o.status = "delivered"
        self.repository.save_completion(d, o)
        if o is not None:
            from app.core.order_updates import publish_order_update
            publish_order_update(o.id, "delivered")

    def list_my_deliveries(self, current_user: User) -> list[dict]:
        """Курьер видит только свои. Admin видит все."""
        if current_user.role == "admin":
            items = self.repository.list_all_deliveries()
        elif current_user.role == "courier":
            items = self.repository.list_deliveries_by_courier(current_user.id)
        else:
            raise ForbiddenError("Только курьер или админ может просматривать список доставок")
        return [
            {"id": d.id, "order_id": d.order_id, "courier_id": d.courier_id, "status": d.status}
            for d in items
        ]

    def get_delivery(self, delivery_id: int, current_user: User) -> dict:
        """Просмотр конкретной доставки с IDOR-проверкой.

        • admin — любую
        • courier — только свою
        • student — только доставку своего заказа
        """
        d = self.repository.get_delivery_by_id(delivery_id)
        if not d:
            raise NotFoundError("Доставка не найдена")

        if current_user.role == "admin":
            pass
        elif current_user.role == "courier":
            if d.courier_id != current_user.id:
                raise ForbiddenError("Курьер видит только свои доставки")
        elif current_user.role == "student":
            order = self.repository.get_order_by_id(d.order_id)
            if not order or order.user_id != current_user.id:
                raise ForbiddenError("Студент видит только доставки своих заказов")
        else:
            raise ForbiddenError("Доступ запрещён")

        return {"id": d.id, "order_id": d.order_id,
                "courier_id": d.courier_id, "status": d.status}
