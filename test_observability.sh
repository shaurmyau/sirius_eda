#!/usr/bin/env bash
# Диагностика Sirius.Еда / практическая работа №9.
# Запускать из корня проекта: bash diagnose_observability.sh
# Полный тест заказа (создаёт и оплачивает реальный тестовый заказ):
# Сквозной тест автоматически регистрирует пользователя, получает токен и использует ITEM_ID=1.
# Тест Sentry (намеренно вызывает HTTP 500):
# RUN_SENTRY_TEST=1 bash diagnose_observability.sh

set -uo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
JAEGER_URL="${JAEGER_URL:-http://127.0.0.1:16686}"
TIMEOUT="${CHECK_TIMEOUT:-5}"
RUN_ORDER_TEST="${RUN_ORDER_TEST:-1}"
RUN_SENTRY_TEST="${RUN_SENTRY_TEST:-0}"
TOKEN="${TOKEN:-}"
ITEM_ID="${ITEM_ID:-}"

STEP=0
PASS=0
FAIL=0
WARN=0
SKIP=0
TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t sirius-diagnostic)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Цвета отключаются при перенаправлении вывода.
if [[ -t 1 ]]; then
  C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'; C_RESET=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_CYAN=""; C_RESET=""
fi

trim_output() {
  local text="$1" max="${2:-5000}"
  if ((${#text} > max)); then
    printf '%s\n... [ответ сокращён; полный вывод см. выше/в логах]' "${text:0:max}"
  else
    printf '%s' "$text"
  fi
}

step_begin() {
  STEP=$((STEP + 1))
  printf '\n%s%d. %s%s\n' "$C_CYAN" "$STEP" "$1" "$C_RESET"
  printf 'Запрос: %s\n' "$2"
}

step_result() {
  local rc="$1" response="$2" kind="${3:-normal}"
  printf 'Ответ:\n'
  if [[ -n "$response" ]]; then trim_output "$response"; printf '\n'; else printf '(пустой ответ)\n'; fi
  if [[ "$kind" == "skip" ]]; then
    SKIP=$((SKIP + 1)); printf '%sРЕЗУЛЬТАТ: ПРОПУЩЕНО%s\n' "$C_YELLOW" "$C_RESET"
  elif [[ "$kind" == "warn" ]]; then
    WARN=$((WARN + 1)); printf '%sРЕЗУЛЬТАТ: ПРЕДУПРЕЖДЕНИЕ%s\n' "$C_YELLOW" "$C_RESET"
  elif ((rc == 0)); then
    PASS=$((PASS + 1)); printf '%sРЕЗУЛЬТАТ: OK%s\n' "$C_GREEN" "$C_RESET"
  else
    FAIL=$((FAIL + 1)); printf '%sРЕЗУЛЬТАТ: ОШИБКА%s\n' "$C_RED" "$C_RESET"
  fi
}

run_step() {
  local title="$1" request="$2" fn="$3" response rc
  shift 3
  step_begin "$title" "$request"
  response="$("$fn" "$@" 2>&1)"; rc=$?
  if ((rc == 2)); then
    step_result 0 "$response" warn
  else
    step_result "$rc" "$response"
  fi
}

skip_step() {
  local title="$1" request="$2" reason="$3"
  step_begin "$title" "$request"
  step_result 0 "$reason" skip
}

warn_step() {
  local title="$1" request="$2" reason="$3"
  step_begin "$title" "$request"
  step_result 0 "$reason" warn
}

http_get() {
  local url="$1" body_file="$TMP_DIR/http_body" headers_file="$TMP_DIR/http_headers"
  local status
  status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" -D "$headers_file" -o "$body_file" -w '%{http_code}' "$url" 2>"$TMP_DIR/curl_error")" || {
    cat "$TMP_DIR/curl_error"
    return 1
  }
  printf 'HTTP %s\n' "$status"
  cat "$body_file"
  [[ "$status" =~ ^2[0-9][0-9]$ ]]
}

check_repo_files() {
  local missing=0 file
  local files=(
    app/main.py app/core/correlation.py app/core/logging.py app/core/metrics.py
    app/core/sentry.py app/core/tracing.py app/core/rabbitmq.py
    app/workers/base.py app/workers/kitchen_consumer.py
    app/workers/order_saga_consumer.py delivery_worker.py delivery_server.py
    prometheus/prometheus.yml
    grafana/provisioning/datasources/prometheus.yml
    grafana/provisioning/dashboards/provider.yml
    grafana/dashboards/sirius-observability.json
  )
  for file in "${files[@]}"; do
    if [[ ! -f "$file" ]]; then printf 'НЕТ: %s\n' "$file"; missing=1; fi
  done
  if ((missing == 0)); then
    printf 'Все %d ожидаемых файлов найдены.\n' "${#files[@]}"
    return 0
  fi
  return 1
}

check_python_deps() {
  local py="python3"
  [[ -x .venv/bin/python ]] && py=".venv/bin/python"
  "$py" - <<'PY'
import importlib
mods = [
    "fastapi", "structlog", "prometheus_fastapi_instrumentator",
    "prometheus_client", "sentry_sdk", "opentelemetry",
    "opentelemetry.sdk", "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.instrumentation.fastapi", "aio_pika", "redis",
]
missing = []
for name in mods:
    try:
        importlib.import_module(name)
        print(f"OK: {name}")
    except Exception as exc:
        missing.append((name, str(exc)))
        print(f"ОТСУТСТВУЕТ: {name}: {exc}")
raise SystemExit(1 if missing else 0)
PY
}

check_python_syntax() {
  local py="python3"
  [[ -x .venv/bin/python ]] && py=".venv/bin/python"
  "$py" -m py_compile \
    app/main.py app/core/correlation.py app/core/logging.py app/core/metrics.py \
    app/core/sentry.py app/core/tracing.py app/core/rabbitmq.py \
    app/workers/base.py app/workers/handlers.py
  printf 'Синтаксис observability-модулей корректен.\n'
}

check_api_menu() {
  http_get "$API_URL/menu/items"
}

check_correlation_header() {
  local cid="diag-$(date +%s)-$RANDOM" body="$TMP_DIR/cid_body" headers="$TMP_DIR/cid_headers" status
  status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" \
    -D "$headers" -o "$body" -w '%{http_code}' \
    -H "X-Correlation-ID: $cid" "$API_URL/menu/items" 2>"$TMP_DIR/cid_err")" || {
      cat "$TMP_DIR/cid_err"; return 1;
    }
  printf 'HTTP %s\n' "$status"
  printf 'Ожидаемый X-Correlation-ID: %s\n' "$cid"
  printf 'Фактический заголовок: '
  grep -i '^x-correlation-id:' "$headers" | tr -d '\r' || true
  printf 'Тело ответа: '; head -c 1200 "$body"; printf '\n'
  [[ "$status" =~ ^2[0-9][0-9]$ ]] && tr -d "\r" < "$headers" | grep -qi "^x-correlation-id: $cid$"
}

check_metrics_endpoint() {
  local body="$TMP_DIR/metrics" status
  status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" -o "$body" -w '%{http_code}' "$API_URL/metrics" 2>"$TMP_DIR/metrics_err")" || {
    cat "$TMP_DIR/metrics_err"; return 1;
  }
  printf 'HTTP %s\n' "$status"
  if [[ "$status" != "200" ]]; then cat "$body"; return 1; fi
  printf 'Найденные ключевые метрики:\n'
  grep -E '^(http_requests_total|http_request_duration_seconds|sirius_orders_create_requests_total|sirius_menu_items_request_duration_seconds)' "$body" | head -n 20 || true
  grep -q 'http_requests_total' "$body"
}

check_compose_config() {
  docker compose config -q && printf 'docker compose config: конфигурация корректна.\n'
}

check_compose_status() {
  docker compose ps
}

check_db() {
  docker compose exec -T db pg_isready -U sirius -d sirius_food
}

check_redis() {
  docker compose exec -T redis redis-cli ping
}

check_rabbitmq() {
  docker compose exec -T rabbitmq rabbitmq-diagnostics -q ping
}

check_rabbit_queues() {
  docker compose exec -T rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
}

check_prometheus_health() {
  http_get "$PROMETHEUS_URL/-/healthy"
}

check_prometheus_targets() {
  local json="$TMP_DIR/targets.json"
  curl -fsS --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" "$PROMETHEUS_URL/api/v1/targets" -o "$json" || return 1
  python3 - "$json" <<'PY'
import json, sys
obj=json.load(open(sys.argv[1], encoding="utf-8"))
targets=obj.get("data", {}).get("activeTargets", [])
if not targets:
    print("Prometheus не обнаружил активных targets.")
    raise SystemExit(1)
for target in targets:
    labels=target.get("labels", {})
    print(f"job={labels.get('job')} health={target.get('health')} scrapeUrl={target.get('scrapeUrl')} lastError={target.get('lastError') or '-'}")
expected={"sirius_app", "rabbitmq", "redis"}
by_job={t.get("labels",{}).get("job"):t.get("health") for t in targets}
missing=expected-set(by_job)
bad=[name for name in expected if by_job.get(name) != "up"]
if missing:
    print("Нет jobs: " + ", ".join(sorted(missing)))
if bad:
    print("Не UP: " + ", ".join(sorted(bad)))
raise SystemExit(1 if missing or bad else 0)
PY
}

check_grafana() {
  http_get "$GRAFANA_URL/api/health"
}

check_jaeger() {
  local json="$TMP_DIR/jaeger_services.json"
  curl -fsS --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" "$JAEGER_URL/api/services" -o "$json" || return 1
  python3 - "$json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding="utf-8"))
services=obj.get("data", [])
print("HTTP 200 — Jaeger API отвечает")
print("Обнаруженные сервисы: " + (", ".join(services) if services else "пока нет; отправьте тестовый запрос через API"))
# Пустой список допустим сразу после старта Jaeger, если ещё не было span'ов.
raise SystemExit(0 if services else 2)
PY
}

check_otlp_port() {
  python3 - <<'PY'
import socket
for host,port in [("127.0.0.1",4317)]:
    try:
        with socket.create_connection((host,port),timeout=3):
            print(f"OTLP gRPC доступен: {host}:{port}")
    except OSError as exc:
        print(f"OTLP gRPC недоступен: {host}:{port}: {exc}")
        raise SystemExit(1)
PY
}

check_consumer_processes() {
  local failed=0 pattern
  for pattern in '[a]pp.workers.kitchen_consumer' '[a]pp.workers.order_saga_consumer' '[d]elivery_worker.py' '[d]elivery_server.py'; do
    if pgrep -af "$pattern"; then :; else printf 'НЕ ЗАПУЩЕН: %s\n' "$pattern"; failed=1; fi
  done
  return "$failed"
}

check_log_files() {
  local failed=0 file
  for file in logs/api.log logs/kitchen.log logs/delivery.log logs/saga.log; do
    if [[ ! -s "$file" ]]; then
      printf 'НЕТ ИЛИ ПУСТОЙ ФАЙЛ: %s\n' "$file"
      failed=1
      continue
    fi
    printf '\n--- %s (последние 3 строки) ---\n' "$file"
    tail -n 3 "$file"
  done
  return "$failed"
}

check_log_json() {
  local file="$1"
  [[ -s "$file" ]] || { printf 'Файл отсутствует или пуст: %s\n' "$file"; return 1; }
  python3 - "$file" <<'PY'
import json,sys
path=sys.argv[1]
valid=0; invalid=0
with open(path,encoding="utf-8",errors="replace") as f:
    lines=f.readlines()[-100:]
for line in lines:
    s=line.strip()
    if not s: continue
    try:
        obj=json.loads(s)
        if isinstance(obj,dict): valid+=1
    except Exception:
        invalid+=1
print(f"{path}: JSON-объектов в последних 100 строках: {valid}; не-JSON строк: {invalid}")
if valid:
    print("Последние структурированные события:")
    shown=0
    for line in reversed(lines):
        try:
            obj=json.loads(line)
            if isinstance(obj,dict):
                print(json.dumps(obj,ensure_ascii=False))
                shown+=1
                if shown>=3: break
        except Exception: pass
raise SystemExit(0 if valid else 2)
PY
}

check_rabbit_exporter() {
  http_get "http://127.0.0.1:15692/metrics"
}

check_redis_exporter() {
  docker compose ps redis-exporter
  local cid
  cid="$(docker compose ps -q redis-exporter)"
  [[ -n "$cid" ]] || { printf 'Контейнер redis-exporter не запущен.
'; return 1; }
  docker inspect -f 'running={{.State.Running}} status={{.State.Status}}' "$cid"
}

check_order_flow() {
  local cid="diag-order-$(date +%Y%m%d%H%M%S)-$RANDOM"
  local email password register_body login_body topup_body
  local token create_body pay_body create_status pay_status order_id
  local item_body item_price topup_amount found=0 file suffix
  local item_status register_status login_status topup_status

  # Отдельная учётная запись для каждого запуска.
  suffix="$(date +%Y%m%d%H%M%S)-$RANDOM"
  email="observability-test-${suffix}@gmail.com"
  password="ObsTest-${suffix}-Aa9!"
  ITEM_ID=1

  register_body="$TMP_DIR/order_register.json"
  login_body="$TMP_DIR/order_login.json"
  topup_body="$TMP_DIR/order_topup.json"
  item_body="$TMP_DIR/order_item.json"
  create_body="$TMP_DIR/order_create.json"
  pay_body="$TMP_DIR/order_pay.json"

  printf 'Тестовый X-Correlation-ID: %s\n' "$cid"
  printf 'Тестовый пользователь: %s\n' "$email"
  printf 'Используемый ITEM_ID: %s\n' "$ITEM_ID"

  # Проверка существования товара с ID=1 и получение его цены.
  item_status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time 15 \
    -o "$item_body" -w '%{http_code}' "$API_URL/menu/items/$ITEM_ID" \
    2>"$TMP_DIR/order_item_err")" || {
      cat "$TMP_DIR/order_item_err"; return 1;
    }
  printf 'Проверка товара: HTTP %s\n' "$item_status"
  cat "$item_body"; printf '\n'
  [[ "$item_status" =~ ^2[0-9][0-9]$ ]] || {
    printf 'Товар с ID=1 не найден или недоступен.\n'; return 1;
  }

  item_price="$(python3 - "$item_body" <<'PYPRICE'
import json, sys
try:
    obj = json.load(open(sys.argv[1], encoding="utf-8"))
    if isinstance(obj, dict):
        obj = obj.get("item", obj)
        print(float(obj.get("price", 0)))
    else:
        print(0)
except Exception:
    print(0)
PYPRICE
)"
  if ! python3 - "$item_price" <<'PYCHECK'
import sys
try:
    value = float(sys.argv[1])
    raise SystemExit(0 if value > 0 else 1)
except Exception:
    raise SystemExit(1)
PYCHECK
  then
    printf 'Не удалось определить положительную цену товара ID=1.\n'
    return 1
  fi

  # Новый пользователь имеет баланс 0. Пополнение на стоимость товара + 10.
  topup_amount="$(python3 - "$item_price" <<'PYAMOUNT'
import math, sys
price = float(sys.argv[1])
amount = math.ceil(price + 10)
if amount > 50000:
    raise SystemExit("Цена товара превышает лимит пополнения 50000")
print(amount)
PYAMOUNT
)" || {
    printf 'Невозможно пополнить баланс для товара ID=1.\n'
    return 1
  }

  printf '\nРегистрация тестового пользователя: POST %s/users/register\n' "$API_URL"
  register_status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time 20 \
    -o "$register_body" -w '%{http_code}' -X POST "$API_URL/users/register" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$email\",\"password\":\"$password\",\"role\":\"student\"}" \
    2>"$TMP_DIR/order_register_err")" || {
      cat "$TMP_DIR/order_register_err"; return 1;
    }
  printf 'Регистрация: HTTP %s\n' "$register_status"
  cat "$register_body"; printf '\n'
  [[ "$register_status" =~ ^2[0-9][0-9]$ ]] || return 1

  printf '\nПолучение токена: POST %s/auth/login\n' "$API_URL"
  login_status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time 20 \
    -o "$login_body" -w '%{http_code}' -X POST "$API_URL/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$email\",\"password\":\"$password\"}" \
    2>"$TMP_DIR/order_login_err")" || {
      cat "$TMP_DIR/order_login_err"; return 1;
    }
  printf 'Авторизация: HTTP %s\n' "$login_status"
  [[ "$login_status" =~ ^2[0-9][0-9]$ ]] || {
    cat "$login_body"; printf '\n'; return 1;
  }

  token="$(python3 - "$login_body" <<'PYTOKEN'
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("access_token", ""))
except Exception:
    print("")
PYTOKEN
)"
  [[ -n "$token" ]] || {
    printf 'В ответе авторизации отсутствует access_token.\n'
    cat "$login_body"; printf '\n'; return 1;
  }
  printf 'Токен получен (значение скрыто).\n'

  printf '\nПополнение баланса на %s: POST %s/users/me/topup\n' "$topup_amount" "$API_URL"
  topup_status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time 20 \
    -o "$topup_body" -w '%{http_code}' -X POST \
    "$API_URL/users/me/topup?amount=$topup_amount" \
    -H "Authorization: Bearer $token" \
    -H "X-Correlation-ID: $cid" \
    2>"$TMP_DIR/order_topup_err")" || {
      cat "$TMP_DIR/order_topup_err"; return 1;
    }
  printf 'Пополнение: HTTP %s\n' "$topup_status"
  cat "$topup_body"; printf '\n'
  [[ "$topup_status" =~ ^2[0-9][0-9]$ ]] || return 1

  printf '\nСоздание заказа: POST %s/orders/create (item_id=1, quantity=1)\n' "$API_URL"
  create_status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time 20 \
    -o "$create_body" -w '%{http_code}' -X POST "$API_URL/orders/create" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    -H "X-Correlation-ID: $cid" \
    -d "{\"item_id\":$ITEM_ID,\"quantity\":1}" \
    2>"$TMP_DIR/order_create_err")" || {
      cat "$TMP_DIR/order_create_err"; return 1;
    }
  printf 'Ответ создания: HTTP %s\n' "$create_status"
  cat "$create_body"; printf '\n'
  [[ "$create_status" =~ ^2[0-9][0-9]$ ]] || return 1

  order_id="$(python3 - "$create_body" <<'PYORDER'
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("order_id", ""))
except Exception:
    print("")
PYORDER
)"
  [[ "$order_id" =~ ^[0-9]+$ ]] || {
    printf 'Не удалось извлечь числовой order_id.\n'; return 1;
  }
  printf 'Извлечён ORDER_ID=%s\n' "$order_id"

  printf '\nПодтверждение оплаты: POST %s/orders/%s/pay\n' "$API_URL" "$order_id"
  pay_status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time 20 \
    -o "$pay_body" -w '%{http_code}' -X POST \
    "$API_URL/orders/$order_id/pay" \
    -H "Authorization: Bearer $token" \
    -H "X-Correlation-ID: $cid" \
    2>"$TMP_DIR/order_pay_err")" || {
      cat "$TMP_DIR/order_pay_err"; return 1;
    }
  printf 'Ответ оплаты: HTTP %s\n' "$pay_status"
  cat "$pay_body"; printf '\n'
  [[ "$pay_status" =~ ^2[0-9][0-9]$ ]] || return 1

  printf '\nОжидание обработки сообщения consumer...\n'
  sleep 5
  for file in logs/api.log logs/kitchen.log logs/delivery.log logs/saga.log; do
    if [[ -f "$file" ]] && grep -Fq "$cid" "$file"; then
      found=$((found + 1))
      printf '\n--- Найден %s в %s ---\n' "$cid" "$file"
      grep -F "$cid" "$file" | tail -n 5
    else
      printf 'Не найден в %s\n' "$file"
    fi
  done

  printf '\nID использован в запросах: %s; совпадение найдено в %d файлах логов.\n' "$cid" "$found"
  [[ "$found" -ge 2 ]]
}
check_sentry_config() {
  local val=""
  if [[ -f .env ]]; then
    val="$(sed -n 's/^SENTRY_DSN=//p' .env | tail -n 1 | tr -d '\r' | tr -d '"' | tr -d "'")"
  fi
  if [[ -n "$val" ]]; then
    printf 'SENTRY_DSN задан в .env (значение скрыто).\n'
    return 0
  fi
  printf 'SENTRY_DSN не задан в .env; Sentry не будет отправлять события.\n'
  return 2
}

check_sentry_test_endpoint() {
  local cid="diag-sentry-$(date +%s)" body="$TMP_DIR/sentry_body" status
  status="$(curl -sS --connect-timeout "$TIMEOUT" --max-time 10 -o "$body" -w '%{http_code}' \
    -H "X-Correlation-ID: $cid" "$API_URL/observability/test-error" 2>"$TMP_DIR/sentry_err")" || {
      cat "$TMP_DIR/sentry_err"; return 1;
    }
  printf 'HTTP %s\n' "$status"
  printf 'X-Correlation-ID: %s\n' "$cid"
  cat "$body"
  [[ "$status" == "500" ]]
}

# Проверяем, что скрипт запущен из корня репозитория.
if [[ ! -f app/main.py || ! -f docker-compose.yml ]]; then
  printf 'ОШИБКА: запусти скрипт из корня sirius_eda (где находятся app/main.py и docker-compose.yml).\n' >&2
  exit 2
fi

printf '%s============================================================%s\n' "$C_CYAN" "$C_RESET"
printf 'Sirius.Еда — автоматическая диагностика Observability\n'
printf 'API: %s\nPrometheus: %s\nGrafana: %s\nJaeger: %s\n' "$API_URL" "$PROMETHEUS_URL" "$GRAFANA_URL" "$JAEGER_URL"
printf '%s============================================================%s\n' "$C_CYAN" "$C_RESET"

run_step 'Файлы проекта observability' 'Проверка существования модулей, конфигураций Prometheus и Grafana' check_repo_files
run_step 'Зависимости Python' 'Импорт FastAPI, structlog, Prometheus, Sentry, OpenTelemetry, aio-pika и Redis' check_python_deps
run_step 'Синтаксис Python' 'python -m py_compile для изменённых модулей observability' check_python_syntax
run_step 'Docker Compose конфигурация' 'docker compose config -q' check_compose_config
run_step 'Состояние Docker-сервисов' 'docker compose ps' check_compose_status
run_step 'PostgreSQL' 'docker compose exec -T db pg_isready -U sirius -d sirius_food' check_db
run_step 'Redis' 'docker compose exec -T redis redis-cli ping' check_redis
run_step 'RabbitMQ' 'docker compose exec -T rabbitmq rabbitmq-diagnostics -q ping' check_rabbitmq
run_step 'Очереди и consumer count RabbitMQ' 'rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers' check_rabbit_queues
run_step 'HTTP API: меню' "GET $API_URL/menu/items" check_api_menu
run_step 'Correlation ID HTTP middleware' "GET $API_URL/menu/items с X-Correlation-ID" check_correlation_header
run_step 'Метрики приложения' "GET $API_URL/metrics" check_metrics_endpoint
run_step 'RabbitMQ Prometheus exporter' 'GET http://127.0.0.1:15692/metrics' check_rabbit_exporter
run_step 'Redis Prometheus exporter' 'GET http://127.0.0.1:9121/metrics' check_redis_exporter
run_step 'Prometheus health' "GET $PROMETHEUS_URL/-/healthy" check_prometheus_health
run_step 'Prometheus targets' "GET $PROMETHEUS_URL/api/v1/targets; ожидаются sirius_app, rabbitmq, redis со статусом UP" check_prometheus_targets
run_step 'Grafana health' "GET $GRAFANA_URL/api/health" check_grafana
run_step 'Jaeger API и список сервисов' "GET $JAEGER_URL/api/services" check_jaeger
run_step 'Jaeger OTLP receiver' 'TCP 127.0.0.1:4317' check_otlp_port
run_step 'Процессы API workers и gRPC доставки' 'pgrep для kitchen_consumer, order_saga_consumer, delivery_worker.py и delivery_server.py' check_consumer_processes
run_step 'Файлы логов процессов' 'Проверка logs/api.log, logs/kitchen.log, logs/delivery.log, logs/saga.log' check_log_files
run_step 'JSON-логи API' 'Проверка последних строк logs/api.log на JSON-объекты' check_log_json logs/api.log
run_step 'JSON-логи кухни' 'Проверка последних строк logs/kitchen.log на JSON-объекты' check_log_json logs/kitchen.log
run_step 'JSON-логи доставки' 'Проверка последних строк logs/delivery.log на JSON-объекты' check_log_json logs/delivery.log
run_step 'JSON-логи Saga' 'Проверка последних строк logs/saga.log на JSON-объекты' check_log_json logs/saga.log

if [[ "$RUN_ORDER_TEST" == "1" ]]; then
  run_step 'Сквозной тест: создание и оплата заказа' 'POST /orders/create, затем POST /orders/{order_id}/pay; проверка одного correlation_id в логах' check_order_flow
else
  skip_step 'Сквозной тест заказа' 'TOKEN, ITEM_ID и RUN_ORDER_TEST=1' 'Не запускался: для отключения установи RUN_ORDER_TEST=0.'
fi

if [[ "$RUN_SENTRY_TEST" == "1" ]]; then
  run_step 'Sentry: тестовое исключение' 'GET /observability/test-error (намеренный HTTP 500; endpoint должен быть включён при DEBUG=true)' check_sentry_test_endpoint
else
  if [[ -f .env ]] && grep -Eq '^SENTRY_DSN=.+' .env; then
    run_step 'Sentry: DSN задан' 'Проверка наличия SENTRY_DSN в .env (значение не выводится)' check_sentry_config
  else
    warn_step 'Sentry: DSN не настроен' 'Проверка SENTRY_DSN в .env' 'Sentry является необязательным модулем и пропустит отправку событий, пока в .env не задан SENTRY_DSN.'
  fi
  warn_step 'Sentry: отправка тестового события' 'Не вызывается без RUN_SENTRY_TEST=1' 'Для проверки отправки намеренной ошибки включи DEBUG=true и OBSERVABILITY_TEST_ENDPOINT=true в окружении API, перезапусти API и запусти RUN_SENTRY_TEST=1 bash diagnose_observability.sh.'
fi

printf '\n%s============================================================%s\n' "$C_CYAN" "$C_RESET"
printf 'ИТОГ ДИАГНОСТИКИ\n'
printf '%sOK: %d%s | %sОШИБКИ: %d%s | %sПРЕДУПРЕЖДЕНИЯ: %d%s | ПРОПУЩЕНО: %d\n' \
  "$C_GREEN" "$PASS" "$C_RESET" "$C_RED" "$FAIL" "$C_RESET" "$C_YELLOW" "$WARN" "$C_RESET" "$SKIP"
printf 'Всего шагов: %d\n' "$STEP"
if ((FAIL > 0)); then
  printf '%sЕсть проверки с ошибками. Исправляй первую ошибку сверху вниз и запусти скрипт повторно.%s\n' "$C_RED" "$C_RESET"
  exit 1
fi
printf '%sКритических ошибок по выполненным проверкам не обнаружено.%s\n' "$C_GREEN" "$C_RESET"
exit 0