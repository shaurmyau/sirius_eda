# Защита практических треков A и B

## Перед показом

Запустить проект: `./start.sh`. Скрипт поднимет PostgreSQL, Redis, RabbitMQ, API, фоновые процессы и применит Alembic-миграции. Swagger: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Демонстрация WebSocket: [http://localhost:3000/order-tracking.html](http://localhost:3000/order-tracking.html).

## Трек A — промокоды и лояльность

1. Администратором создать промокод через `POST /promos` (например, `WELCOME10`, `discount_type=percent`, `discount_value=10`, `max_uses=1`).
2. Клиентом вызвать `POST /orders/create` с `item_id`, `quantity` и `promo_code`. Скидка, проверка лимита, запись использования и списание денег выполняются одной транзакцией; повторное использование отклоняется.
3. После первого оплаченного заказа вызвать `POST /orders/{id}/pay`. Consumer `loyalty` начислит Bronze 3%, Silver 5% или Gold 7%; баланс и история видны через `GET /loyalty/me`.
4. На следующем заказе передать в оплату `{"points_to_spend": 10}`. Списание ограничено 50% суммы и защищено ключом `spend_order_{order_id}`.
5. Отменить заказ через `POST /orders/{id}/cancel`. Consumer-ы `loyalty` и `promo` обработают `order.cancelled`: вернут потраченные баллы, отзовут начисленные и восстановят использование промокода. Компенсации защищены уникальными ключами.
6. Celery Beat раз в час деактивирует промокоды с истёкшим `valid_until`.

**Что показать в коде:** `app/models.py`, миграцию `0005_add_practical_tracks_a_b.py`, `app/modules/orders/repository.py`, `app/workers/handlers.py`, `app/workers/loyalty_consumer.py`, `app/workers/promo_consumer.py`, `app/tasks/orders.py`.

## Трек B — real-time трекинг

1. Войти через `POST /auth/login`, скопировать `access_token`.
2. Открыть `/order-tracking.html`, указать ID своего заказа и токен.
3. Показать snapshot при подключении, затем оплату (статус «готовится»), назначение курьера («в пути») и завершение («доставлен»). Изменения приходят без перезагрузки страницы.
4. Объяснить схему: API публикует JSON в Redis-канал `order_updates`; каждая реплика слушает канал и отправляет сообщение своим локальным WebSocket-клиентам. JWT проверяется при handshake, доступ разрешён только владельцу заказа. Heartbeat проверяет соединение; HTML-клиент переподключается и получает актуальный snapshot.

**Что показать в коде:** `app/modules/orders/websocket.py`, `app/core/websocket_manager.py`, `app/core/order_updates.py`, `frontend/public/order-tracking.html`.

## Проверки

```bash
pytest tests/test_track_a_b.py -v
# 1000 параллельных применений промокода max_uses=1:
python scripts/load_test_tracks.py promo --token "$TOKEN" --item-id 1 --promo-code RACE1000
# 100 WebSocket-клиентов; заказ должен быть отменяемым:
python scripts/load_test_tracks.py ws --token "$TOKEN" --order-id 1 --api-pid "$(pgrep -f 'uvicorn app.main:app' | head -1)"
```

Для трека A создайте отдельный тестовый промокод с `max_uses=1`; для корректного конкурентного теста разных клиентов передайте список JWT через `TRACK_A_TOKENS` (или `--tokens`). Нагрузочный WebSocket-тест инициирует отмену указанного заказа, чтобы измерить доставку одного status event всем соединениям.
