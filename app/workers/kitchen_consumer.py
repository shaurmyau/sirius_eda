"""Consumer кухни. Слушает order.paid и регистрирует заказ в очереди кухни.

Запуск:  python -m app.workers.kitchen_consumer
"""
from app.core.rabbitmq import KITCHEN_QUEUE
from app.workers.base import ConsumerSpec, run
from app.workers.handlers import handle_order_paid_kitchen

SPEC = ConsumerSpec(
    name="kitchen",
    queue=KITCHEN_QUEUE,
    handler=handle_order_paid_kitchen,
    ready_message="[Kitchen] Ждём события order.paid...",
)

if __name__ == "__main__":
    run(SPEC)
