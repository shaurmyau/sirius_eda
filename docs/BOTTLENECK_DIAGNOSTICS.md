# Диагностика узких мест Sirius.Еда

В этой инструкции описаны дополнительные метрики для поиска причины роста latency при нагрузке. Дашборд Grafana: **Sirius.Еда — Bottleneck diagnostics** (UID: sirius-bottleneck-diagnostics).

## Что собирается

### HTTP и приложение

- Стандартные метрики prometheus-fastapi-instrumentator: http_requests_total и http_request_duration_seconds_bucket с низкокардинальными метками handler, method, status. Они позволяют сравнивать RPS, p95/p99 и 5xx по маршрутам.
- sirius_http_requests_in_progress — запросы, находящиеся внутри middleware приложения, с разбивкой по HTTP-методу.
- process_cpu_seconds_total и process_resident_memory_bytes — CPU и RSS процесса Python из стандартного ProcessCollector prometheus-client.

### AnyIO Thread Pool

Метрики sirius_threadpool_total_tokens, sirius_threadpool_borrowed_tokens и sirius_threadpool_waiting_tasks показывают размер общего лимитера синхронных обработчиков, занятые токены и число ожидающих задач. Снимок обновляется каждые 0,5 секунды.

По умолчанию лимит установлен в 40 токенов. Его можно задать переменной окружения ANYIO_THREAD_TOKENS, например:

    ANYIO_THREAD_TOKENS=80 uvicorn app.main:app --host 0.0.0.0 --port 8000

Или передать её скрипту запуска:

    ANYIO_THREAD_TOKENS=80 bash start.sh

Не увеличивайте лимит без проверки CPU и БД: больше потоков может усилить конкуренцию за другие ресурсы. Признак насыщения пула — borrowed_tokens устойчиво близок к total_tokens одновременно с ненулевым waiting_tasks.

### SQLAlchemy и PostgreSQL

SQLAlchemy instrumentation измеряет длительность каждого выполнения cursor query и записывает sirius_db_query_duration_seconds_bucket по ограниченному типу операции (SELECT, INSERT, UPDATE, DELETE, CALL, DDL или OTHER). Текст SQL, параметры, user ID и другие чувствительные значения не становятся Prometheus labels.

Дополнительно доступны:
- sirius_db_query_errors_total — ошибки выполнения запросов;
- sirius_db_pool_size, sirius_db_pool_checked_out, sirius_db_pool_checked_in, sirius_db_pool_overflow — текущее состояние пула соединений.

Время SQL включает round-trip от приложения к БД и обратно; это не чистое серверное CPU-время PostgreSQL. Сопоставляйте его с метриками PostgreSQL, чтобы отличать медленный запрос от ожидания соединения или блокировки.

Добавлен postgres_exporter. Он собирает статистику pg_stat_activity, pg_locks и pg_stat_database; дополнительно включён collector long_running_transactions. Это позволяет увидеть активные сессии, ожидания, блокировки, deadlocks, cache hit ratio и долгие транзакции. Учётная запись sirius используется только в локальной учебной конфигурации; для production выделите отдельную роль мониторинга с минимально необходимыми правами.

### Redis и прикладной кэш меню

Redis exporter продолжает собирать общие показатели Redis: память, подключённые клиенты, количество команд и keyspace hits/misses.

Дополнительно сам репозиторий меню публикует:
- sirius_menu_cache_operations_total{operation,result} — read hit/miss/error, write success/error, lock acquired/timeout/error и исход ожидания lock;
- sirius_menu_cache_operation_duration_seconds_bucket — длительность чтения/записи/lock.

Эти показатели относятся к cache-aside меню, в отличие от глобальных Redis keyspace hit/miss, которые включают все Redis-ключи приложения.

### Ресурсы Linux-хоста и RabbitMQ

Node exporter добавлен для CPU, доступной RAM и файловой системы хоста. Он получает read-only доступ к /proc, /sys и корню файловой системы через bind mounts. Для Docker Desktop или нестандартной ОС набор host-метрик может отличаться.

Существующие метрики RabbitMQ оставлены без изменения; на дашборде показывается глубина kitchen_queue. Если тестируем только чтение меню, очередь обычно не должна расти: сценарий Locust не публикует события заказов без LOCUST_TOKEN.

## Запуск

Из корня репозитория:

    source .venv/bin/activate
    python -m pip install -r requirements.txt
    docker compose config --quiet
    docker compose up -d db redis rabbitmq redis-exporter postgres-exporter node-exporter prometheus grafana jaeger

Запустите API без autoreload для сопоставимых нагрузочных измерений:

    uvicorn app.main:app --host 0.0.0.0 --port 8000

Проверьте:

- API metrics: http://localhost:8000/metrics
- Prometheus targets: http://localhost:9090/targets
- Prometheus query UI: http://localhost:9090/graph
- Grafana: http://localhost:3000

В Prometheus targets должны быть UP jobs sirius_app, postgres, node, rabbitmq и redis. Новый дашборд появится в папке Sirius.Еда.

Если изменялась только конфигурация Prometheus или Compose:

    docker compose up -d --force-recreate postgres-exporter node-exporter prometheus

## Полезные PromQL-запросы

Занятость AnyIO Thread Pool в процентах:

    100 * sirius_threadpool_borrowed_tokens / clamp_min(sirius_threadpool_total_tokens, 1)

Количество задач, ожидающих токен Thread Pool:

    sirius_threadpool_waiting_tasks

p95 SQL round-trip по типам операций:

    histogram_quantile(0.95, sum by (le, operation) (rate(sirius_db_query_duration_seconds_bucket[1m])))

Количество соединений SQLAlchemy, занятых приложением:

    sirius_db_pool_checked_out

p95 HTTP latency по endpoint и методу:

    histogram_quantile(0.95, sum by (le, handler, method) (rate(http_request_duration_seconds_bucket[1m])))

Hit rate именно меню-кэша приложения:

    100 * sum(rate(sirius_menu_cache_operations_total{operation="read",result="hit"}[5m])) / clamp_min(sum(rate(sirius_menu_cache_operations_total{operation="read",result=~"hit|miss"}[5m])), 1e-9)

Загрузка CPU Linux-хоста:

    100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))

## Как интерпретировать

1. Высокая HTTP p95 при низкой SQL p95 и ненулевом Thread Pool waiting — проверьте насыщение AnyIO limiter.
2. Высокая SQL p95 и рост DB pool checked_out — проверьте долгие SQL-запросы, размер пула и соединения.
3. Рост pg_stat_activity по wait state или deadlocks — исследуйте блокировки и транзакции в PostgreSQL.
4. Низкий app cache hit rate либо высокий cache-operation p95 при нормальном SQL p95 — проверьте Redis и Cache-Aside/lock.
5. Одновременный рост host CPU и process CPU — приложение или генератор нагрузки могут конкурировать за CPU. Для нагрузочного теста Locust и API желательно запускать на разных машинах либо учитывать их совместное потребление ресурсов.

Сами по себе метрики указывают на вероятный участок ожидания, но не доказывают причину. Сравнивайте графики в одном временном окне с Locust RPS, p95/p99 и количеством ошибок.
