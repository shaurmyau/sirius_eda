# Сириус.Еда — рефакторинг в Clean Architecture

Все четыре модуля (`users`, `menu`, `orders`, `delivery`) разделены на три слоя:
`router.py`, `service.py`, `repository.py`. Внешнее поведение API не изменилось.

## Что изменилось

| Было (MVP) | Стало |
| --- | --- |
| HTTP, бизнес-правила и SQL в одной функции `router.py` | Три файла на модуль: `router.py` -> `service.py` -> `repository.py` |
| Бизнес-логика работает с ORM-моделями | Бизнес-логика работает с сущностями `app/entities.py` (обычные dataclass) |
| `HTTPException` внутри бизнес-проверок | Сервис бросает `ValueError` / `NotFoundError` / `ForbiddenError`, роутер переводит их в 400 / 404 / 403 |
| Репозитория нет | Абстрактный интерфейс (ABC) в `repository.py` и две реализации: `Sql...` (PostgreSQL) и `InMemory...` |
| Сборка слоёв в каждом обработчике | Одно место сборки: `app/container.py` (composition root) |

Правило зависимостей: `service.py` не импортирует `fastapi` и `sqlalchemy`
(это проверяет тест `tests/test_architecture.py`).

## Структура

```text
app/
├── main.py            # точка входа
├── container.py       # сборка: репозиторий -> сервис (выбор реализации)
├── database.py        # подключение к PostgreSQL
├── models.py          # ORM-модели (SQLAlchemy)
├── entities.py        # сущности предметной области (dataclass)
├── mappers.py         # ORM-модель -> сущность
├── memory_store.py    # хранилище для in-memory репозиториев
├── exceptions.py      # доменные исключения (без fastapi)
├── http_errors.py     # исключение -> HTTP-статус
├── schemas.py         # Pydantic-схемы
└── modules/
    ├── users/     {router.py, service.py, repository.py}
    ├── menu/      {router.py, service.py, repository.py}
    ├── orders/    {router.py, service.py, repository.py}
    └── delivery/  {router.py, service.py, repository.py}
tests/                 # unit-тесты (без СУБД) и API-тест на in-memory
```

## Путь запроса через слои

```mermaid
sequenceDiagram
    participant C as Клиент
    participant R as router.py (API)
    participant S as service.py (бизнес-логика)
    participant P as repository.py (интерфейс)
    participant D as SqlRepository / InMemoryRepository
    C->>R: POST /orders/create
    R->>R: техническая валидация (quantity > 0)
    R->>S: create_order(user_id, item_id, quantity)
    S->>P: get_user_by_id, get_menu_item_by_id
    P->>D: реализация выбирается в container.py
    D-->>S: сущности User, MenuItem
    S->>S: бизнес-правила (доступность, баланс)
    S->>P: save_order_and_update_balance
    S-->>R: order_id или ValueError
    R-->>C: 200 {"status": "success", ...} или 400/403/404
```

Текстовый вариант:

```text
HTTP -> router.py -> service.py -> repository.py (ABC) -> SQL / in-memory
        (Круг 4)     (Круги 1-2)    (Круг 3)
```

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo docker-compose up -d db redis
uvicorn app.main:app --reload
```

Swagger: http://127.0.0.1:8000/docs (SQL-логи выводятся в терминал;
отключить: `SQL_ECHO=0`).

## Тесты

```bash
pytest -v
```

Тесты не требуют PostgreSQL: сервисы проверяются на `InMemory...` репозиториях.

## Замена реализации репозитория

Переключатель находится только в `app/container.py`, файлы `service.py` и
`router.py` не меняются:

```bash
REPO_BACKEND=memory uvicorn app.main:app --reload   # без PostgreSQL, данные в памяти
REPO_BACKEND=postgres uvicorn app.main:app --reload # по умолчанию
```

## Примечания

- Технические проверки (`quantity > 0`, `amount > 0`, формат телефона, цена и длина
  названия блюда) выполняются в роутере, бизнес-правила — в сервисе.
- Заказ создаётся со статусом `processing`, а курьера можно назначить только на
  заказ со статусом `paid` (так было в исходном MVP). Эндпоинта оплаты в проекте нет,
  поэтому для ручной проверки `delivery` статус заказа меняют в БД:
  `UPDATE orders SET status = 'paid' WHERE id = 1;`

## Ролевая модель (RBAC)

Роли описаны не строками в роутере, а **правами** (`permissions`) в `app/permissions.py`:

```
student  -> users:read, users:topup:self, menu:read,
            orders:create, orders:read:self, orders:cancel:self,
            delivery:read:self
cook     -> users:read, users:topup:self, menu:read, menu:write,
            orders:read:any, orders:kitchen
courier  -> users:read, users:topup:self, menu:read,
            orders:read:any, delivery:read:self, delivery:complete:self
admin    -> "*" (все права)
```

Эндпоинт объявляет требуемое право:

```python
@router.post("/items")
def create_menu_item(
    ...,
    _u: User = Depends(require_permission(Perm.MENU_WRITE)),
): ...
```

Проверка «на объект» (IDOR) остаётся в Service и разделяет `*:self` / `*:any`:

- `OrderService.cancel_order` — владелец отменяет через `orders:cancel:self`,
  админ — через `orders:cancel:any`.
- `DeliveryService.get_delivery` — студент видит доставку своего заказа,
  курьер — свою доставку, админ — любую.

Права хранятся в таблице `permissions`, связи — в `role_permissions` (M2M).
Seed выполняется на старте приложения (`seed_permissions()` в `app/database.py`),
поэтому в БД роли и права всегда синхронизированы с `app/permissions.py`.

### Преимущества

- Новая роль (например, `manager`) добавляется одной строкой в матрицу — без правки роутеров.
- Права видны в токене (`GET /users/me` возвращает их списком).
- Разделение «роль → права → эндпоинт» — стандартный подход RBAC.


## Кеширование (ЛР №4)

### Cache-Aside

- `GET /menu/items` — ключ `menu:all`, TTL **300с**.
- `GET /menu/categories/{category}` — ключ `menu:category:{category}`, TTL **600с**.
- Кеш реализован в `app/modules/menu/repository.py` (инфраструктурный слой).
- `service.py` не импортирует `redis` — `tests/test_architecture.py` зелёный.

### Инвалидация

`POST /menu/items` и `PATCH /menu/items/{id}` вызывают
`repository.invalidate_cache()` → удаляются `menu:all` и все
`menu:category:*`. TTL — второй уровень защиты от «залипшего» кеша.

### Защита от cache stampede

При промахе **один** запрос берёт Redis-lock (`lock:menu:all` /
`lock:menu:category:{id}`). Остальные ждут и читают из Redis (double-check
после `acquire()` + polling). PostgreSQL нагружается один раз.

### Прогрев кеша

В `app/main.py` при старте приложения (lifespan) вызывается
`SqlMenuRepository.warm_cache()` — `menu:all` и все `menu:category:*`
заполняются до первого клиента.

### Замеры Locust «до / после»

```bash
locust -f locustfile.py --host=http://127.0.0.1:8000
# http://localhost:8089: 500 users, spawn rate 10
```

| Метрика                            | Без кеша | С кешем |
| ---------------------------------- | -------- | ------- |
| RPS                                | ...      | ...     |
| Среднее время ответа (ms)          | ...      | ...     |
| P95 (ms)                           | ...      | ...     |
| Нагрузка на PostgreSQL (queries/s) | ...      | ...     |

Заполнить после прогона Locust (скриншоты приложить к отчёту).

---

## Лабораторная работа №5: Асинхронность и фоновые задачи (Celery)

### До / После (Замеры)
| Метрика | Синхронно (Baseline) | Асинхронно (Celery) |
| --- | --- | --- |
| Время ответа `POST /orders/create` | ~4000 мс | ~50-100 мс |

### Как запустить инфраструктуру
1. Установите зависимости:
   ```bash
   pip install -r requirements.txt

---

## Практическая работа № 6: gRPC-микросервис delivery

Модуль `delivery` вынесен в отдельный **gRPC-микросервис** по паттерну **Strangler Fig**.

### Архитектура

```
┌──────────────────────────────┐           ┌──────────────────────────────┐
│           Монолит            │           │      delivery-service        │
│      (FastAPI + SQLAlchemy)  │           │    (gRPC, порт 50051)        │
│                              │           │                              │
│  /delivery/assign  ──────────┼── gRPC ──►│  AssignCourier              │
│  /delivery/my      ──────────┼── gRPC ──►│  ListDeliveries / All       │
│  /delivery/{id}    ──────────┼── gRPC ──►│  GetDelivery                │
│  /delivery/{id}/complete ────┼── gRPC ──►│  CompleteDelivery           │
│                              │           │                              │
│  users / orders (своя БД)    │           │  deliveries + orders        │
│  (своя доменная логика)      │           │  (общая PostgreSQL)         │
└──────────────────────────────┘           └──────────────────────────────┘
```

- **Контракт**: `proto/delivery.proto`
- **Сгенерированный код**: `delivery_pb2.py`, `delivery_pb2_grpc.py`
- **Клиент (адаптер)**: `app/modules/delivery/grpc_client.py`
- **Репозиторий**: `app/modules/delivery/grpc_repository.py`
- **Сервер**: `delivery_server.py`

### Запуск

**Терминал 1** — gRPC-сервер:
```bash
source .venv/bin/activate
python delivery_server.py
# Delivery gRPC Server running on port 50051
```

**Терминал 2** — монолит:
```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Проверка: в Swagger вызовите `POST /delivery/assign`. В логах
gRPC-сервера появится запись об обработке.

### Переключение backend'ов

```bash
DELIVERY_BACKEND=grpc     # по умолчанию — вызовы идут в микросервис
DELIVERY_BACKEND=sql      # откат на прямые SQL-запросы (Strangler Fig)
REPO_BACKEND=memory       # полностью in-memory (для тестов)
```

### Обработка сетевых ошибок

`DeliveryGrpcClient._handle_error` транслирует gRPC-коды:

| gRPC | Python | HTTP (через to_http_error) |
|------|--------|-----------------------------|
| `NOT_FOUND`          | `ValueError`      | 404 |
| `UNAVAILABLE`        | `ConnectionError` | 400 (при желании — расширить `http_errors.py` до 503) |
| `DEADLINE_EXCEEDED`  | `TimeoutError`    | 400 |
| `FAILED_PRECONDITION`| `ValueError`      | 400 |

Таймаут по умолчанию — 5 секунд.

### Server Streaming (`TrackDelivery`) — 9 баллов

```bash
python track_delivery.py <delivery_id>
```
Сервер транслирует статусы `in_progress → on_the_way → delivered`
с паузой 2 секунды между ними.

### Bidirectional Streaming (`ChatWithCourier`) — 10 баллов

```bash
python chat_demo.py <delivery_id>
```
Клиент отправляет сообщения из stdin, сервер отвечает в реальном времени.
<!-- lab7-event-driven -->

---

# Практическая работа № 7 — Event-driven архитектура (RabbitMQ, Saga, DLQ)

`OrderService` больше не вызывает кухню и доставку напрямую. При оплате он публикует
событие **OrderPaid** в RabbitMQ и «забывает» о нём; подписчики независимы друг от друга.

## Архитектурная схема

```text
                     POST /orders/{id}/pay
                              │
                      OrderService.pay_order
                      (processing → paid)
                              │ publish  routing_key = order.paid
                              ▼
                 ┌──────────────────────────┐
                 │ exchange  sirius_events  │  (topic, durable)
                 └──────┬───────────┬───────┘
          order.paid    │           │    order.paid                 delivery.failed
                        ▼           ▼                                     ▲  │
                kitchen_queue   delivery_queue                            │  ▼
                        │           │                          order_saga_queue
                        ▼           ▼                                     │
              kitchen_consumer  delivery_worker ──(нет курьера)───────────┘
              (KitchenOrder)    (назначает курьера)  publish delivery.failed
                                                                          │
                                                                          ▼
                                                           order_saga_consumer
                                                           (cancelled + возврат денег)
                                                                          │ publish order.cancelled
                                                                          ▼
                                                                  sirius_events

   Любая очередь:  reject (после 2 неудачных попыток) ──► dlx_exchange ──► *_dlq
```

```mermaid
flowchart LR
    API["POST /orders/ID/pay<br/>OrderService.pay_order"] -- order.paid --> EX(("sirius_events<br/>topic"))
    EX -- order.paid --> KQ[kitchen_queue] --> K[kitchen_consumer]
    EX -- order.paid --> DQ[delivery_queue] --> D[delivery_worker]
    D -- "delivery.failed (нет курьера)" --> EX
    EX -- delivery.failed --> SQ[order_saga_queue] --> S[order_saga_consumer]
    S -- order.cancelled --> EX
    KQ -. reject .-> DLX{{dlx_exchange}}
    DQ -. reject .-> DLX
    SQ -. reject .-> DLX
    DLX --> DLQ[(kitchen_dlq / delivery_dlq / order_saga_dlq)]
```

| Событие (routing key) | Кто публикует | Кто слушает (очередь) |
| --- | --- | --- |
| `order.paid` | `OrderService.pay_order` | кухня (`kitchen_queue`), доставка (`delivery_queue`) |
| `delivery.failed` | `delivery_worker` (нет свободного курьера) | сага заказов (`order_saga_queue`) |
| `order.cancelled` | `order_saga_consumer` | пока никто (точка расширения: уведомления, бонусы) |
| `delivery.assigned` | `delivery_worker` | пока никто |

## Файлы

| Файл | Назначение |
| --- | --- |
| `app/core/rabbitmq.py` | топология (exchange, очереди, DLQ), `publish_event`, `publish_event_sync` |
| `app/workers/handlers.py` | бизнес-логика consumer'ов (БД, идемпотентность), без RabbitMQ |
| `app/workers/base.py` | каркас: ack/retry/DLQ, публикация исходящих событий |
| `app/workers/kitchen_consumer.py` | consumer кухни |
| `delivery_worker.py` | consumer доставки (рядом с `delivery_server.py`) |
| `app/workers/order_saga_consumer.py` | Saga: компенсация при `delivery.failed` |
| `app/workers/dlq_setup.py` | разовое создание DLQ-инфраструктуры |
| `alembic/versions/0004_add_event_tables.py` | таблицы `processed_events`, `kitchen_orders` |

## Запуск

```bash
docker compose up -d db redis rabbitmq        # Management UI: http://localhost:15672 (sirius / sirius)
alembic upgrade head
python -m app.workers.dlq_setup               # DLQ (необязательно: топологию создают и сами consumer'ы)

uvicorn app.main:app --reload                 # монолит
python -m app.workers.kitchen_consumer        # кухня
python delivery_worker.py                     # доставка
python -m app.workers.order_saga_consumer     # сага (компенсации)
# или всё сразу:  ./start.sh
```

Демо: создать заказ (`POST /orders/create`) → `POST /orders/{id}/pay`.
В логе кухни: `[Kitchen] Принят заказ N`; доставки: `[Delivery] Подготовка доставки...`.
Если в системе нет курьера, сработает сага: `[Saga] Заказ N отменён, клиенту ... возвращено ...`.

> Эндпоинт оплаты добавлен в этой работе: деньги списываются при создании заказа
> (`/orders/create`), а `/orders/{id}/pay` переводит заказ `processing → paid` и публикует событие.

## Идемпотентность

RabbitMQ гарантирует **at-least-once**: сообщение может прийти повторно. Каждое событие несёт
`event_id` (uuid). Consumer первым действием вставляет `(event_id, consumer)` в `processed_events`
(UNIQUE) **в той же транзакции**, что и бизнес-изменение: дубликат → пропуск; ошибка → откат вместе с «меткой».
Дополнительно: `kitchen_orders.order_id` UNIQUE — один заказ, одна запись кухни.
Компенсации саги идемпотентны так же (compensation key = `event_id` + проверка статуса заказа).

## Dead Letter Queue

У каждой очереди заданы `x-dead-letter-exchange=dlx_exchange` и `x-dead-letter-routing-key`.
Ошибка обработки (невалидный JSON, нет `event_id`, неизвестный заказ) → сообщение возвращается в очередь
**один раз**, при повторной неудаче → `reject` без requeue → `dlx_exchange` → `kitchen_dlq` / `delivery_dlq` /
`order_saga_dlq`. «Битое» сообщение не блокирует очередь. Проверка: в Management UI опубликовать в
`sirius_events` с ключом `order.paid` тело `not-json` — оно окажется в `kitchen_dlq` и `delivery_dlq`.

## Saga (хореография)

```text
order.paid ──► delivery_worker: свободный курьер есть?  да  → Delivery(in_progress), delivery.assigned
                                                        нет → delivery.failed
delivery.failed ──► order_saga_consumer: заказ → cancelled, баланс += сумма заказа, order.cancelled
```

Центрального оркестратора нет: каждый участник реагирует на события и публикует следующие.

## Тесты

```bash
pytest -m "not integration"        # быстрые: unit + бизнес-логика consumer'ов на SQLite
pytest -m integration -v           # интеграционные: реальный RabbitMQ в контейнере (testcontainers, нужен Docker)
```

Интеграционные тесты (`tests/integration/`) проверяют: обработку корректного сообщения, идемпотентность
при повторной доставке, попадание «битого» сообщения в DLQ (и работоспособность очереди после него),
независимое получение события кухней и доставкой, компенсацию саги. Если Docker недоступен — тесты
пропускаются; можно указать готовый брокер: `RABBITMQ_TEST_URL=amqp://user:pass@host:5672/`
(осторожно: тесты удаляют очереди проекта на этом брокере).

## Ограничения

* Публикация события происходит **после** обновления статуса в БД. Если RabbitMQ недоступен в этот момент,
  событие `order.paid` не будет опубликовано (ошибка логируется). Полное решение — Transactional Outbox
  (в этой работе не реализован).
* Delivery-консьюмер использует общую БД проекта (как и gRPC-сервис из ЛР № 6).

## Ответы на контрольные вопросы

* **Зачем событие, а не gRPC-вызовы?** Слабая связанность: `OrderService` не знает о подписчиках, упавший
  сервис не блокирует оплату, новый подписчик добавляется без правок `OrderService`.
* **Exchange vs Queue.** Exchange маршрутизирует сообщения по ключу и биндингам, не хранит их; Queue хранит
  сообщения до обработки consumer'ом.
* **Идемпотентность.** Повтор операции не меняет результат; реализована через `processed_events` + UNIQUE.
* **Почему at-least-once, а не exactly-once?** Ack может потеряться после обработки (сбой сети/consumer'а),
  брокер не отличит «не обработано» от «не подтверждено» и доставит снова; exactly-once достигается на
  стороне consumer'а идемпотентностью.
* **DLQ.** Очередь для сообщений, которые не удалось обработать: изолирует poison-сообщения и позволяет разобрать их позже.
* **Consumer упал при обработке?** Без ack сообщение вернётся в очередь и будет доставлено повторно
  (поэтому нужна идемпотентность).
* **Событие vs команда.** Событие — факт в прошлом (`OrderPaid`), у него много подписчиков; команда —
  просьба выполнить действие (`AssignCourier`), у неё один адресат.
* **Saga.** Распределённая транзакция как цепочка локальных транзакций с компенсациями: если шаг
  провалился (`DeliveryFailed`), предыдущие откатываются обратными действиями (отмена заказа, возврат денег).
