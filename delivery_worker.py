"""Consumer микросервиса доставки (рядом с delivery_server.py).

Слушает order.paid, назначает свободного курьера. Если курьера нет —
публикует delivery.failed (запускает компенсацию в Saga).

Запуск:  python delivery_worker.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.rabbitmq import DELIVERY_QUEUE  # noqa: E402
from app.workers.base import ConsumerSpec, run  # noqa: E402
from app.workers.handlers import handle_order_paid_delivery  # noqa: E402

SPEC = ConsumerSpec(
    name="delivery",
    queue=DELIVERY_QUEUE,
    handler=handle_order_paid_delivery,
    ready_message="[Delivery] Ждём события order.paid...",
)

if __name__ == "__main__":
    run(SPEC)
