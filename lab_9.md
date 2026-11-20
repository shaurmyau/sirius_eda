# Практическая работа № 9 — Observability в Sirius.Еда

## 1. Запуск проекта

```bash
cd ~/sirius/git/sirius_eda
source .venv/bin/activate
command -v jq >/dev/null 2>&1 || sudo apt-get install -y jq

docker compose up -d db redis rabbitmq prometheus redis-exporter grafana jaeger
./start.sh
```

В новом терминале:

```bash
cd ~/sirius/git/sirius_eda
source .venv/bin/activate

docker compose ps
curl -i http://127.0.0.1:8000/docs
```

## 2. Проверка Correlation ID

```bash
export CID="demo-42"

curl -i http://127.0.0.1:8000/menu/items \
  -H "X-Correlation-ID: $CID"
```

Проверка заголовка `X-Correlation-ID` в ответе.

## 3. Создание и оплата заказа

Вставить действующий access token и ID существующей позиции меню:

```bash
export TOKEN="ВСТАВИТЬ_ACCESS_TOKEN"
export ITEM_ID=1
export CID="demo-42"
```

Создать заказ:

```bash
ORDER_RESPONSE=$(curl -sS -X POST http://127.0.0.1:8000/orders/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: $CID" \
  -d "{\"item_id\": $ITEM_ID, \"quantity\": 1}")

echo "$ORDER_RESPONSE" | jq .
export ORDER_ID=$(echo "$ORDER_RESPONSE" | jq -r '.order_id')
echo "ORDER_ID=$ORDER_ID"

if [[ -z "$ORDER_ID" || "$ORDER_ID" == "null" ]]; then
  echo "Не удалось получить order_id. Проверить TOKEN, ITEM_ID и ответ API."
  exit 1
fi
```

Проверить `ORDER_ID`. Затем оплатить заказ:

```bash
curl -i -X POST "http://127.0.0.1:8000/orders/$ORDER_ID/pay" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Correlation-ID: $CID"
```

Дождаться обработки сообщения RabbitMQ:

```bash
sleep 3
docker compose exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

## 4. Поиск Correlation ID в логах

```bash
grep -F "$CID" logs/api.log
grep -F "$CID" logs/kitchen.log
grep -F "$CID" logs/delivery.log
grep -F "$CID" logs/saga.log
```

Вывод JSON-записей только с нужным Correlation ID:

```bash
for file in logs/api.log logs/kitchen.log logs/delivery.log logs/saga.log; do
  if [ -f "$file" ]; then
    echo "===== $file ====="
    jq -c --arg cid "$CID" 'select(.correlation_id == $cid)' "$file"
  fi
done
```

## 5. Проверка метрик приложения

```bash
curl -sS http://127.0.0.1:8000/metrics | \
  grep -E 'http_requests_total|sirius_orders_create_requests_total|sirius_menu_items_request_duration_seconds' | \
  head -n 40
```

Метрики RabbitMQ и Redis:

```bash
curl -sS http://127.0.0.1:15692/metrics | grep 'rabbitmq_detailed_queue_messages' | head
```

## 6. Prometheus

Проверить доступность Prometheus и состояние targets:

```bash
curl -sS http://127.0.0.1:9090/-/healthy
curl -sS http://127.0.0.1:9090/api/v1/targets | \
  jq -r '.data.activeTargets[] | [.labels.job, .health, .scrapeUrl] | @tsv'
```

Открыть в браузере:

```text
http://localhost:9090/targets
```

PromQL-запросы:

```promql
up
```

```promql
sum(rate(http_requests_total[1m]))
```

```promql
histogram_quantile(0.95, sum by (le) (rate(sirius_menu_items_request_duration_seconds_bucket[1m])))
```

```promql
rabbitmq_detailed_queue_messages{queue="kitchen_queue"}
```

```promql
redis_keyspace_hits_total
```

```promql
redis_keyspace_misses_total
```

## 7. Grafana

Проверить доступность:

```bash
curl -sS http://127.0.0.1:3000/api/health | jq .
```

Открыть в браузере:

```text
http://localhost:3000
```

Данные для входа:

```text
Логин: admin
Пароль: admin
```

Открыть дашборд `Сириус.Еда — Observability`.

## 8. Jaeger и распределённая трассировка

Проверить доступность Jaeger и список сервисов:

```bash
curl -sS http://127.0.0.1:16686/api/services | jq .
```

Открыть в браузере:

```text
http://localhost:16686
```

В интерфейсе Jaeger:

- Service: `sirius-app`.
- Lookback: `Last 15 minutes`.
- Нажать `Find Traces`.
- Открыть trace запроса оплаты заказа.
- Проверить связанные HTTP- и RabbitMQ-span'ы.

## 9. Проверка Sentry (при наличии DSN)

Проверить наличие настроенного DSN, не выводя его значение:

```bash
if grep -qE '^SENTRY_DSN=.+$' .env; then
  echo "SENTRY_DSN задан"
else
  echo "SENTRY_DSN не задан"
fi
```

При наличии DSN и необходимости проверить отправку тестовой ошибки:

```bash
nano .env
```

Установить настройки:

```dotenv
DEBUG=true
OBSERVABILITY_TEST_ENDPOINT=true
SENTRY_DSN=ВАШ_SENTRY_DSN
```

Перезапустить API и выполнить:

```bash
curl -i http://127.0.0.1:8000/observability/test-error \
  -H "X-Correlation-ID: sentry-demo-42"
```

Открыть проект Sentry и проверить тестовое событие с тегом `correlation_id`.

После проверки вернуть:

```dotenv
OBSERVABILITY_TEST_ENDPOINT=false
```

## 10. Автоматическая диагностика

```bash
bash diagnose_observability.sh
```

Сквозная проверка с созданием и оплатой тестового заказа:

```bash
TOKEN="$TOKEN" ITEM_ID="$ITEM_ID" RUN_ORDER_TEST=1 bash diagnose_observability.sh
```

Проверка Sentry (намеренно создаёт ошибку HTTP 500):

```bash
RUN_SENTRY_TEST=1 bash diagnose_observability.sh
```

## 11. Остановка

Остановить процессы приложения в терминале запуска и остановить инфраструктуру:

```bash
docker compose down
```