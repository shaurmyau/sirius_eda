import json
import time
from celery import Task
from app.core.celery_app import celery_app
from app.core.redis import redis_client

class DLQTask(Task):
    """Базовый класс задачи, который при окончательном падении пишет в DLQ."""
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        payload = {
            "task_id": task_id,
            "args": args,
            "kwargs": kwargs,
            "exception": str(exc)
        }
        redis_client.lpush("dlq", json.dumps(payload))
        print(f"\n[DLQ] Задача {self.name}[{task_id}] упала и отправлена в DLQ.\n")

@celery_app.task(bind=True)
def generate_order_pdf(self, order_id: int) -> str:
    """Генерация PDF с проверкой идемпотентности."""
    key = f"pdf_generated:{order_id}"
    if redis_client.exists(key):
        return f"PDF already generated for order {order_id}"
    
    time.sleep(2)
    redis_client.setex(key, 3600, "1")
    return f"PDF generated for order {order_id}"

@celery_app.task(
    base=DLQTask,
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_order_email(self, order_id: int, email: str) -> str:
    """Отправка email с ретраями и DLQ."""
    time.sleep(1)
    if order_id % 5 == 0:
        raise Exception("Email service unavailable")
    return f"Email sent to {email} for order {order_id}"

@celery_app.task(
    base=DLQTask,
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_order_sms(self, order_id: int, phone: str) -> str:
    time.sleep(1)
    return f"SMS sent to {phone} for order {order_id}"

@celery_app.task
def cleanup_old_task_logs() -> str:
    print("[Beat] Cleaning up old task logs...")
    return "Cleanup complete"



@celery_app.task
def deactivate_expired_promo_codes() -> int:
    """Celery Beat: деактивирует промокоды с истёкшим valid_until."""
    from datetime import datetime, timezone
    from app.database import SessionLocal
    from app.models import PromoCode

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = SessionLocal()
    try:
        rows = (
            db.query(PromoCode)
            .filter(PromoCode.is_active.is_(True), PromoCode.valid_until <= now)
            .all()
        )
        for row in rows:
            row.is_active = False
        db.commit()
        count = len(rows)
        print(f"[Beat] Deactivated expired promo codes: {count}")
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
