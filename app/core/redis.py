"""Redis-клиент и хелпер для проверки соединения."""
import logging

import redis

from app.core.config import settings

log = logging.getLogger(__name__)

redis_client = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


def check_redis_connection() -> bool:
    try:
        return bool(redis_client.ping())
    except Exception as exc:
        log.warning("Redis unavailable: %s", exc)
        return False
