"""Consumer восстановления использования промокодов по OrderCancelled."""
from app.core.rabbitmq import PROMO_QUEUE
from app.workers.base import ConsumerSpec, run
from app.workers.handlers import handle_order_cancelled_promo

SPEC = ConsumerSpec(
    name="promo",
    queue=PROMO_QUEUE,
    handler=handle_order_cancelled_promo,
    ready_message="[Promo] Ждём события order.cancelled...",
)

if __name__ == "__main__":
    run(SPEC)
