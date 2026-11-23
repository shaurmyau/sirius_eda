# Практическая работа № 10 — проверка на 10 баллов

Реализация покрывает оба дополнительных задания из ТЗ: Pact и mutmut. Проверки разделены
по критериям, поэтому их можно демонстрировать по отдельности, а затем запускать общей
командой.

## 1. Быстрая проверка по критериям

Из корня репозитория:

| Критерий | Команда | Что показать |
|---|---|---|
| Unit-тесты и пирамида тестов | `./scripts/check_practical_work_10.sh fast` | Быстрые тесты сервисов и API без реального Docker |
| 6–7: PostgreSQL Testcontainers | `./scripts/check_practical_work_10.sh integration` | `tests/integration/test_orders_postgres.py`: чистый PostgreSQL 15, Alembic upgrade, создание заказа через HTTP, запись в БД и списание баланса |
| 6–7: RabbitMQ Testcontainers | та же команда | Реальная доставка сообщений, идемпотентность, fan-out, DLQ и Saga в `tests/integration/test_consumers_integration.py` |
| 6–7: Locust | `./scripts/run_load_test.sh` | RPS, failure rate, median/p95/p99 и CSV/HTML отчёты для 50/100/200 пользователей |
| 8: GitHub Actions | вкладка Actions → **Sirius EDA tests** | Checks `tests` и `mutmut` на push и PR |
| 9: Pact | `./scripts/check_practical_work_10.sh contract` | Pact V3 Async Message: проверка kitchen consumer и provider-сообщения из `OrderService.pay_order` |
| 10: mutmut | `./scripts/check_practical_work_10.sh mutation` | Запуск мутантов только для `OrderService`, список killed/survived |

Полный прогон: `./scripts/check_practical_work_10.sh all`. Для интеграционных тестов
нужен запущенный Docker. В CI Docker доступен на GitHub-hosted runner; при `CI=true`
недоступность Docker считается ошибкой, а не успешным пропуском.

## 2. Testcontainers: что именно изолировано

Фикстура `postgres_url` в `tests/integration/conftest.py` поднимает временный
`postgres:15` контейнер на тестовую сессию. Схема создаётся миграциями
`alembic upgrade head`, а не вручную подогнанными таблицами. Фикстура
`postgres_session` открывает внешнюю транзакцию и использует savepoint для коммитов
репозитория; после теста транзакция откатывается. Контейнер останавливается по завершении
сессии. Можно указать отдельную тестовую БД переменной `POSTGRES_TEST_URL`, если нужен
уже запущенный PostgreSQL.

Тест `test_create_order_persists_and_debits_balance_in_postgres` проходит через
FastAPI endpoint и SQL repository и проверяет:
- HTTP-ответ и идентификатор заказа;
- сохранение заказа в PostgreSQL со статусом `processing`;
- количество и связи заказа;
- списание ровно рассчитанной суммы с баланса.

RabbitMQ остаётся отдельной интеграционной фикстурой: каждый тест очищает очереди и
exchange проекта; production/dev брокер не используется, если явно не задан
`RABBITMQ_TEST_URL`.

## 3. Locust: нагрузка и узкое место

Запустить приложение и зависимости:

```bash
docker compose up -d db redis rabbitmq
alembic upgrade head
python seed.py
uvicorn app.main:app --reload
```

Во втором терминале:

```bash
./scripts/run_load_test.sh
```

Сценарий `locustfile.py` моделирует чтение всего меню (вес 7), категории (вес 2),
карточки блюда (вес 1) и создание заказа (вес 1, когда передан токен). Для создания
заказов заранее зарегистрируйте пользователя, пополните баланс, получите JWT и задайте:

```bash
export LOCUST_TOKEN="<access_token>"
export LOCUST_ITEM_ID=1
```

Опции можно переопределить без изменения кода:

```bash
LOCUST_HOST=http://127.0.0.1:8000 \
LOCUST_DURATION=90s LOCUST_SPAWN_RATE=10 LOCUST_STAGES="50 100 200" \
./scripts/run_load_test.sh
```

Результаты сохраняются в `reports/locust/`: `*_stats.csv`,
`*_stats_history.csv` и `*.html`. В таблице статистики смотрите:
- **Requests/s** — фактический RPS;
- **Median / 95% / 99%** — latency;
- **Failure Count / Failure %** — ошибки;
- как эти показатели меняются между 50, 100 и 200 пользователями.

Для защиты зафиксируйте порог, на котором p95 становится больше 1000 мс или ошибки
превышают 1%. Одновременно откройте Prometheus/Grafana: <http://localhost:9090>,
<http://localhost:3000> (admin/admin). Проверьте CPU/память хоста, задержки и
число запросов к PostgreSQL, Redis cache hit/miss, а также длину RabbitMQ очередей.
Называйте узкое место только по вашим фактическим CSV и графикам: заранее заданные
RPS/latency в документации не являются замером. На чистой машине может потребоваться
уменьшить `LOCUST_STAGES` или `LOCUST_DURATION`.

## 4. Pact: контракт кухни и монолита

Контракт описывает минимальный набор, на который опирается consumer: `event_id`,
`order_id`, `total`, `currency`. Провайдер добавляет и сохраняет `amount`,
`customer_id` и `occurred_at` для обратной совместимости с delivery/Saga.

Файл `app/core/order_events.py` — единственная фабрика OrderPaid. Она добавляет
`total` и `currency=RUB`, оставляя `amount` как legacy alias. Тест
`tests/contracts/test_order_paid_pact.py`:
1. генерирует Pact V3 asynchronous message interaction от имени кухни;
2. отдаёт контрактный пример настоящему `handle_order_paid_kitchen`;
3. вызывает реальный `OrderService.pay_order` и перехватывает публикацию `order.paid`;
4. проверяет сформированное сообщение provider verifier'ом.

Как показать, что тест ловит несовместимость: в отдельной локальной копии временно
переименуйте `total` в фабрике на `amount`, запустите `pytest tests/contracts -v`
и покажите падение Pact provider verification. Верните изменение после демонстрации.
В PR и в основной ветке намеренно остаётся совместимая версия.

## 5. Mutmut: проверка качества unit-тестов

Конфигурация `setup.cfg` ограничивает мутацию модулем
`app/modules/orders/service.py`, а набор тестов — `tests/unit/`. Это делает
эксперимент быстрым и воспроизводимым, не перемешивая его с RabbitMQ/PostgreSQL и
сетевыми тестами.

```bash
pytest tests/unit -v
mutmut run
mutmut results
```

Сначала зафиксируйте исходное число выживших мутантов, затем добавьте тест,
который проверяет пропущенную ветку/границу, и повторите `mutmut run`.
Основные защитные проверки находятся в `tests/unit/test_orders_service.py`:
баланс и количество, неизвестный пользователь/блюдо, недоступное блюдо, владелец
и чужой заказ, admin, статусы cancel/pay, публикация суммы/валюты и legacy amount.
В CI результаты прикладываются артефактом **mutmut-results**.

## 6. CI и блокировка merge

Workflow `.github/workflows/test.yml` запускается при каждом push, pull request
в `main` и вручную. Check names: `tests` и `mutmut`. В `tests` запускаются
обычные/контрактные тесты и интеграционные PostgreSQL + RabbitMQ Testcontainers.
Job `mutmut` запускается только после успешного `tests`.

Чтобы GitHub физически запрещал merge при красном CI, откройте
**Settings → Rules → Rulesets** (или **Settings → Branches**), создайте правило
для `main`, включите **Require status checks to pass before merging** и добавьте
оба обязательных check: `tests`, `mutmut`. Включите **Require a pull request**
и запрет прямого push, если это допустимо в настройках курса. Сам workflow
публикует checks, но запрет merge задаётся настройкой репозитория.

Для демонстрации red CI используйте отдельную ветку: временно добавьте в unit-тест
заведомо ложный assert, push, дождитесь красного check `tests`, затем удалите
assert и убедитесь, что workflow снова зелёный. Не оставляйте намеренно сломанный
тест в PR/main.

## 7. Основные файлы для ответа преподавателю

| Баллы | Файлы |
|---|---|
| 6–7 Testcontainers / Postgres | `tests/integration/conftest.py`, `tests/integration/test_orders_postgres.py`, `alembic/versions/` |
| 6–7 Testcontainers / RabbitMQ | `tests/integration/conftest.py`, `tests/integration/test_consumers_integration.py` |
| 6–7 Locust | `locustfile.py`, `scripts/run_load_test.sh` |
| 8 CI | `.github/workflows/test.yml` |
| 9 Pact | `app/core/order_events.py`, `tests/contracts/test_order_paid_pact.py` |
| 10 mutmut | `setup.cfg`, `tests/unit/test_orders_service.py` |
| Проверка всей работы | `scripts/check_practical_work_10.sh`, этот файл |
