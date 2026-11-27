"""Публикация realtime-обновлений заказа через Redis Pub/Sub."""
import json
import logging
from datetime import datetime, timezone

from app.core.redis import redis_client

log = logging.getLogger("orders.realtime")
ORDER_UPDATES_CHANNEL = "order_updates"


def publish_order_update(order_id: int, status: str) -> None:
    payload = {
        "type": "order.status",
        "order_id": int(order_id),
        "status": status,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        redis_client.publish(ORDER_UPDATES_CHANNEL, json.dumps(payload, ensure_ascii=False))
    except Exception:
        # Redis — транспорт realtime-уведомления; недоступность не откатывает бизнес-транзакцию.
        log.warning("Не удалось опубликовать realtime-статус заказа %s", order_id, exc_info=True)
