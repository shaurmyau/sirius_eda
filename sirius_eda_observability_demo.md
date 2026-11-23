# Sirius.Еда — демонстрация лабораторной работы Observability

> Команды рассчитаны на запуск из корня репозитория `sirius_eda`.
> Перед защитой проверь, что Docker, Docker Compose и виртуальное окружение проекта настроены.

## 1. Ссылки всякие

| Сервис | Адрес | Что показывать |
|---|---|---|
| FastAPI / Swagger | http://localhost:8000/docs | API, создание и оплата заказа |
| Prometheus | http://localhost:9090 | Метрики и состояние targets |
| Prometheus Targets | http://localhost:9090/targets | Все источники метрик со статусом `UP` |
| Grafana | http://localhost:3000 | Дашборд «Сириус.Еда — Observability» |
| Jaeger | http://localhost:16686 | Распределённые трассировки заказа |
| RabbitMQ Management | http://localhost:15672 | Очереди, сообщения и consumers |

Дополнительные HTTP endpoints (не обязательно открывать в браузере):

- Метрики приложения: http://localhost:8000/metrics
- Prometheus health: http://localhost:9090/-/healthy
- Grafana health: http://localhost:3000/api/health
- Jaeger services API: http://localhost:16686/api/services
- RabbitMQ Prometheus exporter: http://localhost:15692/metrics
- Redis Exporter: http://localhost:9121/metrics

Учетные данные Grafana и RabbitMQ зависят от `.env` и `docker-compose.yml` проекта. Используй значения, заданные в своей конфигурации.

## 2. Команды запуска и проверки

### 2.1. Перейти в корень проекта и запустить сервисы

```bash
cd /path/to/sirius_eda
./start.sh
```

Если проект уже запущен, повторно запускать `start.sh` не требуется.

### 2.2. Запустить общую диагностику

```bash
bash test_observability.sh
```

Скрипт проверяет наличие файлов observability, зависимости и синтаксис Python, конфигурацию Compose, доступность PostgreSQL / Redis / RabbitMQ, API, метрики, Prometheus targets, Grafana, Jaeger, процессы сервисов и JSON-логи.

### 2.3. Запустить сквозной тест заказа

```bash
RUN_ORDER_TEST=1 bash test_observability.sh
```

Скрипт создаёт тестового пользователя, авторизуется, пополняет баланс, создаёт заказ, оплачивает его и ищет один Correlation ID в логах.

В тесте используется `ITEM_ID=1`. Убедись, что товар с таким ID существует.

### 2.4. Проверить JSON-метрики и targets вручную

```bash
# Метрики приложения
curl -s http://localhost:8000/metrics | head -n 40

# Prometheus health
curl -s http://localhost:9090/-/healthy

# Статусы targets Prometheus
curl -s http://localhost:9090/api/v1/targets \
  | jq -r '.data.activeTargets[] | [.labels.job, .health, .scrapeUrl] | @tsv'

# RabbitMQ exporter
curl -s http://localhost:15692/metrics | head -n 40

# Jaeger: зарегистрированные сервисы
curl -s http://localhost:16686/api/services | jq .
```

Ожидаемые jobs Prometheus: `sirius_app`, `rabbitmq`, `redis`; их состояние должно быть `up`.

### 2.5. Найти Correlation ID в логах

Если известен ID тестового заказа:

```bash
CID="значение-correlation-id"

grep -F "$CID" logs/api.log
grep -F "$CID" logs/kitchen.log
grep -F "$CID" logs/delivery.log
grep -F "$CID" logs/saga.log
```

Проверить только JSON-записи с этим ID:

```bash
for file in logs/api.log logs/kitchen.log logs/delivery.log logs/saga.log; do
  echo "===== $file ====="
  jq -c --arg cid "$CID" 'select(.correlation_id == $cid)' "$file"
done
```

Для критерия сквозной корреляции обязательно покажи совпадение ID как минимум в `logs/api.log` и `logs/kitchen.log`.

### 2.6. Проверить метрики в Prometheus

Открой http://localhost:9090 и выполни запросы в поле Expression:

```promql
rate(http_requests_total[5m])
```

```promql
rabbitmq_detailed_queue_messages
```

```promql
up
```

Точные имена метрик зависят от версий библиотек и exporter. Если запрос не возвращает данные, открой `/metrics` или страницу `/targets` и выбери реально экспортируемое имя метрики.

### 2.7. Проверить Grafana

Открой http://localhost:3000, войди с учетными данными из конфигурации и выбери дашборд:

`Сириус.Еда — Observability`

Поставь временной диапазон `Last 15 minutes` и создай несколько запросов / заказов, чтобы на графиках появились данные.

## 3. Дополнительные баллы

### 3.1. Sentry — демонстрация на 9 баллов

В `.env` должны быть настроены:

```dotenv
SENTRY_DSN=твой_DSN
DEBUG=true
OBSERVABILITY_TEST_ENDPOINT=true
```

Перезапусти API после изменения переменных окружения.

Запусти тест:

```bash
RUN_SENTRY_TEST=1 bash test_observability.sh
```

Скрипт вызывает тестовый endpoint и проверяет ожидаемый HTTP 500. Для подтверждения интеграции открой проект в Sentry и покажи полученное событие, тег `correlation_id` и контекст ошибки.

Тестовый endpoint предназначен только для локальной демонстрации. Не оставляй его включённым в публичном production-окружении.

### 3.2. OpenTelemetry + Jaeger — демонстрация на 10 баллов

1. Убедись, что Jaeger запущен и доступен: http://localhost:16686
2. Выполни сквозной тест заказа:

```bash
RUN_ORDER_TEST=1 bash test_observability.sh
```

3. В Jaeger выбери сервис `sirius-app`, временной диапазон `Last 15 minutes` и нажми `Find Traces`.
4. Открой trace и покажи HTTP span, публикацию RabbitMQ и span consumer кухни, связанные одним trace context.

Сам факт доступности Jaeger не доказывает наличие трассировки: для 10 баллов нужно показать реально полученный trace.

## 4. Критерии оценки и файлы реализации

| Баллы / критерий | Где реализовано | Что показать |
|---|---|---|
| **0–3** — Correlation ID отсутствует, логи неструктурированные, метрик нет | К проекту не относится: базовые требования реализованы | Показать следующие пункты |
| **4–5** — Correlation ID в монолите, частично структурированные логи | `app/core/correlation.py`, `app/core/logging.py`, `app/main.py` | HTTP-запрос с `X-Correlation-ID`, ответ и запись в `logs/api.log` |
| **6–7** — ID проходит через сервисы и RabbitMQ, JSON-логи, Prometheus собирает метрики | `app/core/correlation.py`, `app/core/rabbitmq.py`, `app/workers/base.py`, `app/workers/kitchen_consumer.py`, `app/workers/handlers.py`, `app/core/logging.py`, `app/core/metrics.py`, `app/main.py`, `prometheus/prometheus.yml`, `docker-compose.yml` | Один ID в логах API и кухни; JSON-строки; `/metrics`; Prometheus Targets со статусом `UP` |
| **8** — всё из 6–7 + Grafana + расследование заказа | Дополнительно: `grafana/dashboards/sirius-observability.json`, `grafana/provisioning/datasources/prometheus.yml`, `grafana/provisioning/dashboards/provider.yml`, `test_observability.sh`, `lab_9.md` | Дашборд Grafana и поиск одного заказа по Correlation ID в логах |
| **9** — всё из 8 + Sentry | `app/core/sentry.py`, `app/core/correlation.py`, `app/workers/base.py`, `app/main.py`, `observability.env.example` | Реальное событие в Sentry с тегом `correlation_id` |
| **10** — всё из 9 + OpenTelemetry и распределённый trace в Jaeger | `app/core/tracing.py`, `app/core/rabbitmq.py`, `app/workers/base.py`, `app/main.py`, `docker-compose.yml`, `observability.env.example` | Реальный trace в Jaeger: HTTP → RabbitMQ publish → Kitchen consumer |

### Ключевые файлы — назначение

| Файл | Назначение |
|---|---|
| `app/core/correlation.py` | HTTP middleware, получение / установка Correlation ID, контекст |
| `app/core/logging.py` | Настройка структурированных логов |
| `app/core/metrics.py` | Метрики приложения |
| `app/core/rabbitmq.py` | Публикация сообщений, передача Correlation ID и trace context |
| `app/workers/base.py` | Общая обработка сообщений consumer, извлечение контекста, логирование и spans |
| `app/workers/kitchen_consumer.py` | Consumer кухни |
| `app/workers/handlers.py` | Обработчики событий и бизнес-логика |
| `app/core/sentry.py` | Инициализация Sentry |
| `app/core/tracing.py` | Инициализация OpenTelemetry и OTLP exporter |
| `app/main.py` | Подключение middleware, логирования, метрик, Sentry и tracing к FastAPI |
| `prometheus/prometheus.yml` | Источники сбора метрик Prometheus |
| `grafana/dashboards/sirius-observability.json` | Панели дашборда Grafana |
| `docker-compose.yml` | Инфраструктурные сервисы: Prometheus, Grafana, Jaeger, RabbitMQ и exporters |
| `test_observability.sh` | Автоматическая диагностика компонентов и сквозной тест заказа |
| `observability.env.example` | Пример переменных окружения для observability |