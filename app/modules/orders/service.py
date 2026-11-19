"""Слой бизнес-логики orders. IDOR-проверка в сервисе."""
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from app.entities import User
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.modules.orders.repository import OrderRepository
from app.tasks.orders import generate_order_pdf, send_order_email, send_order_sms

CANCELLABLE = ("processing", "paid")

log = logging.getLogger("orders.events")

# publisher(routing_key, payload) — внедряется из container.py (RabbitMQ).
# Сервис не знает про aio_pika: слой остаётся «чистым».
EventPublisher = Callable[[str, dict], None]


class OrderService:
    def __init__(self, repository: OrderRepository, publisher: EventPublisher | None = None):
        self.repository = repository
        self.publisher = publisher

    def create_order(self, user_id, item_id, quantity) -> int:
        u = self.repository.get_user_by_id(user_id)
        if not u:
            raise NotFoundError("Пользователь не найден")
        it = self.repository.get_menu_item_by_id(item_id)
        if not it:
            raise NotFoundError("Блюдо не найдено")
        if not it.is_available:
            raise ValueError("Блюдо недоступно")
        total = it.price * quantity
        if u.balance < total:
            raise ValueError("Недостаточно средств на балансе студента")

        order_id = self.repository.save_order_and_update_balance(
            user_id, item_id, quantity, u.balance - total
        )

        # Вызов фоновых задач
        generate_order_pdf.delay(order_id)
        send_order_email.delay(order_id, u.email)
        if u.phone:
            send_order_sms.delay(order_id, u.phone)

        return order_id

    def pay_order(self, order_id: int, current_user: User) -> None:
        """Оплата (подтверждение) заказа: processing → paid + событие OrderPaid.

        Средства списываются при создании заказа (create_order), поэтому здесь
        мы фиксируем оплату и публикуем событие. Кто его получит (кухня,
        доставка, бонусы) — забота подписчиков, а не OrderService.
        """
        o = self.repository.get_order_by_id(order_id)
        if not o:
            raise NotFoundError("Заказ не найден")
        if o.user_id != current_user.id and current_user.role != "admin":
            raise ForbiddenError("Нельзя оплатить чужой заказ")
        if o.status == "paid":
            raise ConflictError("Заказ уже оплачен")
        if o.status != "processing":
            raise ValueError("Заказ нельзя оплатить в текущем статусе")

        item = self.repository.get_menu_item_by_id(o.item_id)
        amount = float(item.price * o.quantity) if item else 0.0

        self.repository.update_order_status(order_id, "paid")
        self._publish("order.paid", {
            "event_id": str(uuid.uuid4()),  # ключ идемпотентности для consumer'ов
            "order_id": o.id,
            "customer_id": o.user_id,
            "amount": amount,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })

    def _publish(self, routing_key: str, payload: dict) -> None:
        if self.publisher is None:
            return
        try:
            self.publisher(routing_key, payload)
        except Exception:
            # Без Transactional Outbox событие при недоступном брокере теряется.
            log.exception("Не удалось опубликовать %s (order_id=%s)",
                          routing_key, payload.get("order_id"))

    def cancel_order(self, order_id: int, current_user: User) -> None:
        o = self.repository.get_order_by_id(order_id)
        if not o:
            raise NotFoundError("Заказ не найден")
        if o.user_id != current_user.id and current_user.role != "admin":
            raise ForbiddenError("Нельзя отменить чужой заказ")
        if o.status not in CANCELLABLE:
            raise ValueError("Заказ нельзя отменить в текущем статусе")
        self.repository.update_order_status(order_id, "cancelled")

    def list_my_orders(self, current_user: User) -> list[dict]:
        """Список заказов текущего пользователя. IDOR закрыт по построению:
        берём user_id только из JWT, а не из параметра запроса."""
        orders = self.repository.list_orders_by_user(current_user.id)
        return [
            {"id": o.id, "item_id": o.item_id, "quantity": o.quantity, "status": o.status}
            for o in orders
        ]
