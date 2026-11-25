# Шпаргалка к защите практической работы № 10

> Открой этот файл во время защиты. Команды рассчитаны на запуск из корня репозитория `sirius_eda` в Ubuntu.  
> Репозиторий: [shaurmyau/sirius_eda](https://github.com/shaurmyau/sirius_eda) · [GitHub Actions](https://github.com/shaurmyau/sirius_eda/actions)

## 0. Самый быстрый запуск перед демонстрацией

В терминале из корня проекта:

```bash
source .venv/bin/activate
docker info
PORT=3001 bash start.sh
```

`start.sh` поднимает инфраструктуру Docker Compose, применяет миграции, загружает seed-данные и запускает процессы приложения: API, gRPC delivery, consumers кухни/доставки/Saga, Celery worker/beat и Flower. Если установлен Node.js и есть `frontend/node_modules`, дополнительно запускается Next.js frontend.

Открой второй терминал для команд и логов:

```bash
docker compose ps
tail -f logs/api.log logs/grpc.log logs/kitchen.log logs/delivery.log logs/saga.log
```

Остановить процессы — `Ctrl+C` в терминале `start.sh`. Затем остановить контейнеры (данные именованного volume PostgreSQL сохраняются):

```bash
docker compose down
```

**Почему `PORT=3001`:** Grafana из Compose занимает порт `3000`; frontend запускается на `3001`, чтобы не конфликтовать с Grafana. Фактический адрес Next.js проверь в `logs/web.log`.

## 1. Ссылки для браузера и сетевые порты

| Что демонстрировать | Адрес | Что показывает |
|---|---|---|
| API Swagger | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | Все HTTP-эндпоинты, схемы запросов и ответы; основной экран для демонстрации API |
| API ReDoc | [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc) | Альтернативная документация API (при включённом DEBUG) |
| Метрики FastAPI | [http://127.0.0.1:8000/metrics](http://127.0.0.1:8000/metrics) | Prometheus-метрики HTTP-приложения |
| Frontend | [http://localhost:3001/menu](http://localhost:3001/menu) | Витрина меню; запускается, если доступен Node.js и установлен frontend |
| RabbitMQ Management | [http://localhost:15672](http://localhost:15672) | Exchanges, queues, bindings, сообщения и DLQ; логин/пароль: `sirius / sirius` |
| Prometheus | [http://localhost:9090](http://localhost:9090) · [targets](http://localhost:9090/targets) | Сбор метрик и состояние scrape-targets |
| Grafana | [http://localhost:3000](http://localhost:3000) | Дашборды мониторинга; логин/пароль: `admin / admin` |
| Jaeger UI | [http://localhost:16686](http://localhost:16686) | Distributed traces, spans и связи между сервисами |
| Flower (Celery) | [http://localhost:5555](http://localhost:5555) | Состояние Celery workers и фоновых задач |
| Locust Web UI (опционально) | [http://localhost:8089](http://localhost:8089) | Интерактивный интерфейс Locust; headless-скрипт ниже его не запускает |

### Порты без браузерного интерфейса

| Порт | Сервис | Для чего |
|---:|---|---|
| `5432` | PostgreSQL | SQL-подключение приложения |
| `6379` | Redis | Cache-Aside и блокировки cache stampede |
| `5672` | RabbitMQ AMQP | Публикация и получение событий |
| `15692` | RabbitMQ Prometheus exporter | Метрики RabbitMQ для Prometheus |
| `50051` | Delivery gRPC | RPC-вызовы монолита к delivery-сервису |
| `4317` / `4318` | Jaeger OTLP | Приём OpenTelemetry traces (gRPC / HTTP) |

## 2. Команды проверок — краткая таблица

Все команды запускать из корня проекта в активированном `.venv`.

| Что проверяем | Команда | Что должно подтвердиться |
|---|---|---|
| Быстрые unit/API/не-интеграционные тесты | `bash scripts/check_practical_work_10.sh fast` | Тесты без запуска Testcontainers |
| PostgreSQL + RabbitMQ integration | `bash scripts/check_practical_work_10.sh integration` | Временные контейнеры Testcontainers; Docker Engine должен быть доступен |
| Pact contract | `bash scripts/check_practical_work_10.sh contract` | Совместимость OrderPaid producer и kitchen consumer |
| Mutmut | `bash scripts/check_practical_work_10.sh mutation` | Focused unit suite и mutation testing OrderService |
| Locust нагрузочный профиль | `bash scripts/run_load_test.sh` | Последовательные headless-прогоны на 50/100/200 пользователей |
| Полный прогон | `bash scripts/check_practical_work_10.sh all` | fast → integration → focused unit → mutmut |

### Отдельные команды, если нужно показать конкретный тест

```bash
# Все быстрые тесты: без integration-маркера
pytest -m "not integration" -v

# Интеграционные тесты PostgreSQL и RabbitMQ
pytest tests/integration -m integration -v

# Только Pact
pytest tests/contracts -m contract -v

# Только focused unit tests для OrderService
pytest tests/unit -v

# Полный mutation run с чистым кэшем
rm -rf .mutmut-cache
mutmut run
mutmut results
```

**Для integration:** нужен работающий Docker Engine (`docker info`). Тесты сами поднимают одноразовые PostgreSQL 15 и RabbitMQ контейнеры. Не направляй `POSTGRES_TEST_URL` или `RABBITMQ_TEST_URL` на рабочую/общую базу или брокер: фикстуры интеграционных тестов очищают топологию RabbitMQ.

### Результат mutmut, полученный локально

Последний присланный локальный прогон: **59 killed из 61, 2 survived, mutation score 96,7%**. Выжившие мутанты — `4` (имя logger) и `6` (type alias `EventPublisher`). Это результат локального запуска, не утверждение о статусе GitHub Actions.

## 3. Нагрузочное тестирование Locust

Запуск стандартного сценария (по умолчанию 60 секунд на этап, 50 → 100 → 200 пользователей):

```bash
bash scripts/run_load_test.sh
```

Скрипт headless: он не открывает веб-интерфейс Locust, а сохраняет результаты в `reports/locust/`:

- `users-*_stats.csv` — requests, RPS, errors, median/p95/p99;
- `users-*_stats_history.csv` — динамика метрик;
- `users-*.html` — HTML-отчёт.

Переопределить нагрузку:

```bash
LOCUST_HOST=http://127.0.0.1:8000 \
LOCUST_DURATION=90s LOCUST_SPAWN_RATE=10 LOCUST_STAGES="50 100 200" \
bash scripts/run_load_test.sh
```

Чтобы в сценарии выполнялось не только чтение меню, но и создание заказов, сначала зарегистрируй пользователя, войди через `POST /auth/login`, скопируй access token и задай:

```bash
export LOCUST_TOKEN="<access_token>"
export LOCUST_ITEM_ID=1
bash scripts/run_load_test.sh
```

Для интерактивного Locust UI (в отдельном терминале вместо headless-скрипта):

```bash
locust -f locustfile.py --host=http://127.0.0.1:8000
```

После запуска открыть [http://localhost:8089](http://localhost:8089).

## 4. Последовательность демонстрации API

Основной экран — [Swagger](http://127.0.0.1:8000/docs). В Swagger можно выбрать endpoint, посмотреть Pydantic-схему и выполнить запрос.

1. **Регистрация и авторизация:** `POST /users/register`, затем `POST /auth/login`. Access token вставить через кнопку **Authorize** в Swagger.
2. **Профиль и RBAC:** `GET /users/me` — профиль, роль и эффективные permissions.
3. **Баланс:** `POST /users/me/topup` — пополнение своего баланса; `GET /users/me` — проверить результат.
4. **Меню:** `GET /menu/items`, `GET /menu/categories/food`, `GET /menu/items/{item_id}`.
5. **Заказ:** `POST /orders/create` → `GET /orders/my`. При создании проверяются пользователь, доступность блюда и баланс; заказ сохраняется со статусом `processing`.
6. **Оплата и событие:** `POST /orders/{order_id}/pay`. Статус меняется на `paid`, OrderService публикует `order.paid` в RabbitMQ.
7. **Доставка:** `POST /delivery/assign`, `GET /delivery/my`, `GET /delivery/{delivery_id}`, `PATCH /delivery/{delivery_id}/complete`. Для назначения курьера заказ должен быть оплачен.
8. **Отмена:** `POST /orders/{order_id}/cancel` — демонстрация проверки владельца/прав.

Для показа event-driven-сценария после оплаты открой RabbitMQ Management и логи:

```bash
tail -f logs/kitchen.log logs/delivery.log logs/saga.log
```

Если нет свободного курьера, delivery consumer публикует `delivery.failed`; Saga выполняет компенсацию: отменяет заказ и возвращает деньги. В RabbitMQ можно показать очереди `kitchen_queue`, `delivery_queue`, `order_saga_queue` и соответствующие `*_dlq`.

## 5. Карта баллов: критерий → сервис → файлы → демонстрация

### Баллы 1–5 — базовая архитектура и пирамида тестирования

Это основной слой приложения: разделение HTTP / бизнес-логики / доступа к данным, DI/composition root, базовые unit/API/architecture/RBAC tests.

> В существующей проектной документации подробно разнесены дополнительные критерии 6–10; базовые критерии 1–5 описаны как архитектура и пирамида тестов, без отдельной нумерации каждого подпункта. Поэтому ниже приведена общая карта базового уровня, а не выдуманное соответствие «балл 1 — конкретно этот файл».

| Часть | Реализация |
|---|---|
| Composition root и выбор backend | `app/container.py` — сборка сервисов и выбор SQL / in-memory / gRPC реализаций |
| Доменные сущности и ошибки | `app/entities.py`, `app/exceptions.py`, `app/http_errors.py`, `app/mappers.py` |
| Auth | `app/modules/auth/router.py`, `service.py`, `repository.py` — login, refresh-token rotation |
| Users | `app/modules/users/router.py`, `service.py`, `repository.py` — регистрация, профиль, баланс |
| Menu | `app/modules/menu/router.py`, `service.py`, `repository.py` — чтение/изменение меню и Redis cache |
| Orders | `app/modules/orders/router.py`, `service.py`, `repository.py` — создание, оплата, отмена, список заказов |
| Delivery | `app/modules/delivery/router.py`, `service.py`, `repository.py` — назначение курьера, просмотр и завершение доставки |
| RBAC и зависимости | `app/permissions.py`, `app/core/dependencies.py` |
| Базовые тесты | `tests/test_services.py`, `tests/test_api_memory.py`, `tests/test_architecture.py`, `tests/test_rbac.py`, `tests/test_register_role.py`, `tests/test_menu_item_endpoint.py`, `tests/test_pay_order.py`, `tests/test_event_handlers.py`, `tests/conftest.py` |

**Что показать:** Swagger + быстрые тесты. В `service.py` находятся бизнес-правила, в `router.py` — HTTP-эндпоинты/проверка входных данных, в `repository.py` — абстракция хранения и реализации. `app/container.py` связывает слои.

### Баллы 6–7 — интеграционные проверки, брокер и нагрузка

| Критерий | Сервис / назначение | Ключевые файлы | Команда / демонстрация |
|---|---|---|---|
| PostgreSQL Testcontainers | Временный PostgreSQL 15, миграция Alembic, HTTP → OrderService → SQL repository → БД; проверка сохранения заказа и списания баланса | `tests/integration/conftest.py`, `tests/integration/test_orders_postgres.py`, `alembic/versions/`, `app/modules/orders/repository.py` | `bash scripts/check_practical_work_10.sh integration` |
| RabbitMQ Testcontainers | Реальный брокер; fan-out кухни/доставки, idempotency, retry/DLQ и Saga-компенсация | `tests/integration/conftest.py`, `tests/integration/test_consumers_integration.py`, `app/core/rabbitmq.py`, `app/workers/base.py`, `app/workers/handlers.py`, `app/workers/kitchen_consumer.py`, `delivery_worker.py`, `app/workers/order_saga_consumer.py` | Та же команда integration; затем RabbitMQ UI и логи workers |
| Locust | Нагрузка на чтение меню/категории/карточки блюда и авторизованное создание заказа; CSV/HTML отчёты | `locustfile.py`, `scripts/run_load_test.sh` | `bash scripts/run_load_test.sh`; отчёты в `reports/locust/` |

**Важные части event-driven-сценария:**

- `app/core/rabbitmq.py` — exchange `sirius_events`, очереди, bindings, DLX/DLQ, publish.
- `app/workers/handlers.py` — обработчики кухни, доставки и Saga; идемпотентность по `event_id`.
- `app/workers/base.py` — общий consumer-каркас, ack/retry/DLQ.
- `app/workers/kitchen_consumer.py` — kitchen consumer.
- `delivery_worker.py` — delivery consumer.
- `app/workers/order_saga_consumer.py` — Saga consumer.

### Балл 8 — CI/CD-проверки в GitHub Actions

| Что | Файл / объект |
|---|---|
| Workflow | `.github/workflows/test.yml` |
| Job/check `tests` | Быстрые/контрактные проверки и PostgreSQL + RabbitMQ integration |
| Job/check `mutmut` | Focused unit tests и mutation testing; запускается после `tests` |
| Где смотреть | [GitHub Actions](https://github.com/shaurmyau/sirius_eda/actions) → последний запуск **Sirius EDA tests** |

Workflow запускается при push, pull request в `main` и вручную. Физическая блокировка merge требует отдельного правила репозитория: Settings → Rules / Rulesets → Require status checks → `tests`, `mutmut`.

### Балл 9 — Pact contract testing

| Что | Файл |
|---|---|
| Формирование сообщения OrderPaid | `app/core/order_events.py` — `event_id`, `order_id`, `total`, `currency=RUB`; сохранён legacy `amount` |
| Consumer/provider contract test | `tests/contracts/test_order_paid_pact.py` |
| Реальный kitchen handler | `app/workers/handlers.py` — `handle_order_paid_kitchen` |
| Реальный producer | `app/modules/orders/service.py` — `OrderService.pay_order` |
| Команда | `bash scripts/check_practical_work_10.sh contract` |

Тест использует Pact V3 asynchronous message: пример сообщения проходит через обработчик кухни, а provider verification проверяет фактическое событие, сформированное `OrderService.pay_order`.

### Балл 10 — Mutation testing (mutmut)

| Что | Файл |
|---|---|
| Конфигурация целевого mutation scope | `setup.cfg` — только `app/modules/orders/service.py`, тесты из `tests/unit/` |
| Focused unit suite | `tests/unit/test_orders_service.py` |
| Код, в котором внедряются мутанты | `app/modules/orders/service.py` |
| Команды | `pytest tests/unit -v` → `mutmut run` → `mutmut results` |

Последний подтверждённый локальный результат: **59/61 killed (96,7%)**. Два выживших мутанта: `4` (имя logger) и `6` (type alias). Не называй mutation score результатом CI — это отдельный локальный прогон.

## 6. Карта основных сервисов проекта

| Сервис / модуль | Ответственность | Главные файлы |
|---|---|---|
| Auth | Вход, refresh-токены | `app/modules/auth/router.py`, `app/modules/auth/service.py`, `app/modules/auth/repository.py`, `app/core/jwt.py` |
| Users | Регистрация, профиль, роли/права, баланс | `app/modules/users/router.py`, `app/modules/users/service.py`, `app/modules/users/repository.py`, `app/permissions.py` |
| Menu | Каталог, категории, создание/обновление блюд, кеширование | `app/modules/menu/router.py`, `app/modules/menu/service.py`, `app/modules/menu/repository.py`, `app/core/redis.py` |
| Orders | Создание, оплата, отмена и список заказов; публикация OrderPaid | `app/modules/orders/router.py`, `app/modules/orders/service.py`, `app/modules/orders/repository.py`, `app/core/order_events.py` |
| Delivery (gRPC) | Назначение, получение и завершение доставки; streaming tracking/chat | `proto/delivery.proto`, `delivery_server.py`, `delivery_pb2.py`, `delivery_pb2_grpc.py` |
| Delivery adapter | Вызов gRPC из монолита через прежний интерфейс репозитория | `app/modules/delivery/grpc_client.py`, `app/modules/delivery/grpc_repository.py`, `app/container.py` |
| Event workers | Kitchen, delivery и Saga; retry, idempotency, DLQ | `app/core/rabbitmq.py`, `app/workers/base.py`, `app/workers/handlers.py`, `app/workers/kitchen_consumer.py`, `delivery_worker.py`, `app/workers/order_saga_consumer.py` |
| Монолит/API | Подключение роутеров, middleware, metrics, tracing, startup | `app/main.py`, `app/container.py` |

## 7. Что открыть преподавателю в первую очередь

1. [Swagger — API](http://127.0.0.1:8000/docs): регистрация/логин, меню, заказ, оплата, доставка.
2. [RabbitMQ](http://localhost:15672): `sirius / sirius`; показать exchange, queues и DLQ.
3. [Grafana](http://localhost:3000) и [Prometheus targets](http://localhost:9090/targets): показать мониторинг и сбор метрик.
4. [Jaeger](http://localhost:16686): показать traces, если сервисы уже обработали запросы.
5. В терминале — integration/Pact/mutmut команды и mutation result 96,7%.
6. В GitHub — [Actions](https://github.com/shaurmyau/sirius_eda/actions), workflow **Sirius EDA tests**.

**Если времени мало:** сначала запусти `PORT=3001 bash start.sh`, открой Swagger и RabbitMQ, затем покажи `bash scripts/check_practical_work_10.sh all` или соответствующие проверки по отдельности.
