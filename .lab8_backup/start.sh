#!/usr/bin/env bash
# ==============================================================================
# Запуск всех процессов Sirius.Food в одном терминале.
# Включает: БД, RabbitMQ, gRPC, API, Celery, воркеры событий (ЛР №7).
# Логи — в ./logs/*.log, Ctrl+C гасит всё.
# ==============================================================================
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs
source .venv/bin/activate

# Если beat уже работал, файл-лок мог остаться от убитого процесса
rm -f celerybeat-schedule celerybeat-schedule-shm celerybeat-schedule-wal

PIDS=()
cleanup() {
  echo -e "\n==> Останавливаю всё..."
  for pid in "${PIDS[@]}"; do 
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "==> Все процессы остановлены."
}
trap cleanup EXIT INT TERM

start() {
  local name=$1; shift
  echo "==> Запуск: $name"
  "$@" > "logs/$name.log" 2>&1 &
  PIDS+=($!)
}

echo "==> 0. Поднимаем инфраструктуру (Docker)..."
docker compose up -d db redis rabbitmq > /dev/null

echo -n "==> Ожидание PostgreSQL..."
until docker compose exec -T db pg_isready -U sirius -d sirius_food >/dev/null 2>&1; do
  echo -n "."
  sleep 1
done
echo " OK"

echo "==> Ожидание RabbitMQ (AMQP)..."
python - << 'PY'
import asyncio, sys, time
import aio_pika
from app.core.config import settings

async def probe():
    c = await aio_pika.connect(settings.RABBITMQ_URL, timeout=3)
    await c.close()

for i in range(30):
    try:
        asyncio.run(probe())
        print("AMQP готов")
        sys.exit(0)
    except Exception:
        time.sleep(1)
sys.exit("AMQP не поднялся: docker logs --tail 60 sirius_rabbitmq")
PY

echo "==> Применяем миграции БД (Alembic)..."
alembic upgrade head > logs/alembic.log 2>&1 || { echo "Ошибка миграций! Смотрите logs/alembic.log"; exit 1; }

echo "==> Настраиваем инфраструктуру очередей (DLQ)..."
if ! python -m app.workers.dlq_setup > logs/dlq_setup.log 2>&1; then
    echo "ВНИМАНИЕ: dlq_setup завершился с ошибкой. Последние строки лога:"
    tail -n 10 logs/dlq_setup.log
    echo "Продолжаем запуск (воркеры умеют переподключаться и создавать топологию)..."
fi

echo "==> 1. Запуск gRPC-сервиса доставки..."
start grpc python delivery_server.py
sleep 1

echo "==> 2. Запуск Event-Driven воркеров (ЛР № 7)..."
start kitchen  python -m app.workers.kitchen_consumer
start delivery python delivery_worker.py
start saga     python -m app.workers.order_saga_consumer

echo "==> 3. Запуск FastAPI монолита..."
start api uvicorn app.main:app --reload

echo "==> 4. Запуск Celery (Worker + Beat)..."
start worker celery -A app.core.celery_app worker --loglevel=info --pool=solo
start beat   celery -A app.core.celery_app beat   --loglevel=info

echo "==> 5. Запуск Flower (мониторинг Celery)..."
start flower celery -A app.core.celery_app flower

echo -e "\n======================================================="
echo "Всё запущено!"
echo "Логи воркеров событий (ЛР №7):"
echo "  tail -f logs/kitchen.log logs/delivery.log logs/saga.log"
echo ""
echo "Остальные логи:"
echo "  tail -f logs/api.log logs/grpc.log logs/worker.log"
echo ""
echo "Swagger: http://127.0.0.1:8000/docs"
echo "RabbitMQ: http://localhost:15672 (sirius / sirius)"
echo "======================================================="
echo "Нажмите Ctrl+C, чтобы остановить всё."
echo ""

# Держим скрипт живым, пока не Ctrl+C
while true; do sleep 1; done