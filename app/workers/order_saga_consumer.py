"""Участник саги на стороне заказов/платежей (хореография).

Слушает delivery.failed и компенсирует оплату:
  заказ → cancelled, деньги возвращаются на баланс, публикуется order.cancelled.

Запуск:  python -m app.workers.order_saga_consumer
"""
from app.core.rabbitmq import ORDER_SAGA_QUEUE
from app.workers.base import ConsumerSpec, run
from app.workers.handlers import handle_delivery_failed

SPEC = ConsumerSpec(
    name="order_saga",
    queue=ORDER_SAGA_QUEUE,
    handler=handle_delivery_failed,
    ready_message="[Saga] Ждём события delivery.failed...",
)

if __name__ == "__main__":
    run(SPEC)
