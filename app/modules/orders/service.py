"""Слой бизнес-логики orders. IDOR-проверка в сервисе."""
import logging
import uuid
from collections.abc import Callable
from decimal import Decimal

from app.core.order_events import build_order_paid_event
from app.entities import User
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.modules.orders.repository import OrderRepository
from app.tasks.orders import generate_order_pdf, send_order_email, send_order_sms

CANCELLABLE = ("processing", "paid", "on_the_way")

log = logging.getLogger("orders.events")

# publisher(routing_key, payload) — внедряется из container.py (RabbitMQ).
# Сервис не знает про aio_pika: слой остаётся «чистым».
EventPublisher = Callable[[str, dict], None]


class OrderService:
    def __init__(self, repository: OrderRepository, publisher: EventPublisher | None = None):
        self.repository = repository
        self.publisher = publisher

    def create_order(self, user_id, item_id, quantity, promo_code: str | None = None) -> int:
        if quantity <= 0:
            raise ValueError("Количество должно быть больше нуля")
        u = self.repository.get_user_by_id(user_id)
        if not u:
            raise NotFoundError("Пользователь не найден")
        it = self.repository.get_menu_item_by_id(item_id)
        if not it:
            raise NotFoundError("Блюдо не найдено")
        if not it.is_available:
            raise ValueError("Блюдо недоступно")

        # Проверка баланса, блокировка промокода, создание заказа и фиксация
        # PromoCodeUsage выполняются репозиторием в одной DB-транзакции.
        order_id = self.repository.save_order_and_update_balance(
            user_id, item_id, quantity, None, promo_code
        )

        generate_order_pdf.delay(order_id)
        send_order_email.delay(order_id, u.email)
        if u.phone:
            send_order_sms.delay(order_id, u.phone)
        return order_id

    def pay_order(
        self,
        order_id: int,
        current_user: User,
        points_to_spend: Decimal = Decimal("0.00"),
    ) -> None:
        """Подтверждает оплату, при необходимости списывает баллы и публикует OrderPaid."""
        o = self.repository.get_order_by_id(order_id)
        if not o:
            raise NotFoundError("Заказ не найден")
        if o.user_id != current_user.id and current_user.role != "admin":
            raise ForbiddenError("Нельзя оплатить чужой заказ")
        if o.status == "paid":
            raise ConflictError("Заказ уже оплачен")
        if o.status != "processing":
            raise ValueError("Заказ нельзя оплатить в текущем статусе")

        if points_to_spend and Decimal(str(points_to_spend)) > 0:
            self.repository.spend_loyalty_points(order_id, o.user_id, Decimal(str(points_to_spend)))
            o = self.repository.get_order_by_id(order_id)

        item = self.repository.get_menu_item_by_id(o.item_id)
        amount = float(o.total_amount) if o.total_amount is not None else (
            float(item.price * o.quantity) if item else 0.0
        )
        self.repository.update_order_status(order_id, "paid")
        self._notify_order_status(order_id, "preparing")
        self._publish(
            "order.paid",
            build_order_paid_event(
                order_id=o.id,
                customer_id=o.user_id,
                total=amount,
            ),
        )

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
        self._notify_order_status(order_id, "cancelled")
        self._publish("order.cancelled", {
            "event_id": str(uuid.uuid4()),
            "order_id": o.id,
            "customer_id": o.user_id,
            "promo_code_id": o.promo_code_id,
            "discount_amount": str(o.discount_amount or 0),
            "points_spent": str(o.points_spent or 0),
            "reason": "customer_cancelled",
        })

    @staticmethod
    def _notify_order_status(order_id: int, status: str) -> None:
        from app.core.order_updates import publish_order_update
        publish_order_update(order_id, status)

    def list_my_orders(self, current_user: User) -> list[dict]:
        """Список заказов текущего пользователя. IDOR закрыт по построению:
        берём user_id только из JWT, а не из параметра запроса."""
        orders = self.repository.list_orders_by_user(current_user.id)
        return [
            {"id": o.id, "item_id": o.item_id, "quantity": o.quantity, "status": o.status}
            for o in orders
        ]
