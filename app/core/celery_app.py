from celery import Celery
from kombu import Queue, Exchange
from app.core.config import settings

celery_app = Celery(
    "sirius_food",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=['app.tasks.orders'], 
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.task_queues = (
    Queue("default", Exchange("default"), routing_key="default"),
)
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

celery_app.conf.beat_schedule = {
    "cleanup-old-task-logs-every-minute": {
        "task": "app.tasks.orders.cleanup_old_task_logs",
        "schedule": 60.0,
    },
    "deactivate-expired-promo-codes-every-hour": {
        "task": "app.tasks.orders.deactivate_expired_promo_codes",
        "schedule": 3600.0,
    },
}