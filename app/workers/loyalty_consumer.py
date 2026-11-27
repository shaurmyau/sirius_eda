"""Consumer начислений и компенсаций баллов программы лояльности."""
from app.core.rabbitmq import LOYALTY_QUEUE
from app.workers.base import ConsumerSpec, run
from app.workers.handlers import handle_order_cancelled_loyalty, handle_order_paid_loyalty


def handle_loyalty_event(db, payload):
    routing = payload.get("_routing_key")
    if routing == "order.cancelled":
        return handle_order_cancelled_loyalty(db, payload)
    return handle_order_paid_loyalty(db, payload)


SPEC = ConsumerSpec(
    name="loyalty",
    queue=LOYALTY_QUEUE,
    handler=handle_loyalty_event,
    ready_message="[Loyalty] Ждём события order.paid / order.cancelled...",
)

if __name__ == "__main__":
    run(SPEC)
