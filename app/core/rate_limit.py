"""Rate limiting на Redis (9 баллов)."""
import logging

from fastapi import HTTPException, Request

from app.core.config import settings

log = logging.getLogger(__name__)

try:
    from redis import Redis
    _redis = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
except Exception:
    _redis = None


def rate_limit(max_requests: int = 5, window: int = 60):
    def checker(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED or _redis is None:
            return
        ip = request.client.host if request.client else "unknown"
        key = f"rl:{ip}:{request.url.path}"
        try:
            n = _redis.incr(key)
            if n == 1:
                _redis.expire(key, window)
            if n > max_requests:
                raise HTTPException(status_code=429, detail="Too many requests")
        except HTTPException:
            raise
        except Exception as e:
            log.warning("redis unavailable: %s", e)

    return checker
