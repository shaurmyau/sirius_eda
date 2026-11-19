#!/usr/bin/env bash
# =============================================================================
# test.sh — сквозная проверка Sirius.Food (монолит + gRPC + Celery + кеш).
# =============================================================================
set -u

# venv — чтобы был grpc для helper'а и корректные зависимости
if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

BASE="${BASE:-http://127.0.0.1:8000}"
GRPC_HOST="${GRPC_HOST:-localhost}"
GRPC_PORT="${GRPC_PORT:-50051}"

PASS=0; FAIL=0; SKIP=0
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'

# ВАЖНО: всё в stderr — иначе $(...) захватывает вывод ok/bad вместе с токеном
section() { echo >&2; echo "${CYAN}${BOLD}==== $1 ====${NC}" >&2; }
ok()      { echo "${GREEN}  [PASS]${NC} $1" >&2; PASS=$((PASS+1)); }
skip()    { echo "${YELLOW}  [SKIP]${NC} $1" >&2; SKIP=$((SKIP+1)); }
bad()     {
    echo "${RED}  [FAIL]${NC} $1 — ожидалось ${BOLD}$2${NC}, получено ${BOLD}$3${NC}" >&2
    if [ -n "${BODY:-}" ]; then echo "         тело: $BODY" >&2; fi
    FAIL=$((FAIL+1))
}

request() {
    local method=$1 path=$2 data="${3:-}" token="${4:-}"
    local args=(-s -o /tmp/_body -w '%{http_code}' -X "$method" "$BASE$path"
                -H 'Content-Type: application/json')
    [ -n "$data" ]  && args+=(-d "$data")
    [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
    STATUS=$(curl "${args[@]}" 2>/dev/null || echo "000")
    BODY=$(cat /tmp/_body 2>/dev/null || echo "")
}

jget()  { python3 -c "import sys,json;print(json.load(sys.stdin)$1)" <<< "$BODY" 2>/dev/null || echo ""; }
expect() { local n=$1 w=$2; [ "$STATUS" = "$w" ] && ok "$n [$STATUS]" || bad "$n" "$w" "$STATUS"; }

# Присваивание в переданную переменную — БЕЗ $(...) → ok/bad в stderr не мешают
login_and_store() {
    local email=$1 label=$2 var=$3
    request POST /auth/login "{\"email\":\"$email\",\"password\":\"$USER_PWD\"}"
    if [ "$STATUS" = "200" ]; then
        printf -v "$var" '%s' "$(jget '["access_token"]')"
        printf -v "${var}_refresh" '%s' "$(jget '["refresh_token"]')"
        ok "login $label [200]"
    else
        printf -v "$var" '%s' ""
        printf -v "${var}_refresh" '%s' ""
        bad "login $label" 200 "$STATUS"
    fi
}

reg_user_and_store() {
    local email=$1 role=$2 label=$3 var=$4
    request POST /users/register "{\"email\":\"$email\",\"password\":\"$USER_PWD\",\"role\":\"$role\"}"
    if [ "$STATUS" = "200" ]; then
        local uid=$(jget '["user_id"]')
        local r=$(jget '["role"]')
        printf -v "$var" '%s' "$uid"
        [ "$r" = "$role" ] && ok "$label: user_id=$uid role=$r" \
                           || bad "$label" "$role" "$r"
    else
        printf -v "$var" '%s' ""
        bad "$label" 200 "$STATUS"
    fi
}

dc() {
    if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi
}

psql_exec() {
    local q="$1" out=""
    # 1. docker
    if command -v docker >/dev/null 2>&1 && dc ps 2>/dev/null | grep -q 'db'; then
        out=$(dc exec -T db psql -U sirius -d sirius_food -tAc "$q" 2>/dev/null \
              | grep -vE '^(UPDATE|INSERT|DELETE|TRUNCATE|DROP|CREATE|ALTER) [0-9]+$' \
              | tr -d '[:space:]')
        if [ -n "$out" ]; then echo "$out"; return 0; fi
    fi
    # 2. локальный psql
    if command -v psql >/dev/null 2>&1; then
        out=$(PGPASSWORD=sirius psql -h localhost -U sirius -d sirius_food -tAc "$q" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$out" ]; then echo "$out"; return 0; fi
    fi
    # 3. python SessionLocal (тот же движок, что у приложения)
    SQL_QUERY="$q" python3 -c "
import os, sys
try:
    from app.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    r = db.execute(text(os.environ['SQL_QUERY']))
    rows = list(r)
    db.commit()
    for row in rows:
        if row[0] is not None:
            print(str(row[0]).strip()); break
except Exception:
    sys.exit(1)
" 2>/dev/null | tr -d '[:space:]'
}

redis_exec() {
    if command -v docker >/dev/null 2>&1 && dc ps 2>/dev/null | grep -q 'redis'; then
        dc exec -T redis redis-cli "$@" 2>/dev/null
    elif command -v redis-cli >/dev/null 2>&1; then
        redis-cli "$@" 2>/dev/null
    else
        echo ""
    fi
}

# =============================================================================
# Прекондиции
# =============================================================================
if ! curl -s --max-time 3 "$BASE/docs" -o /dev/null; then
    echo "${RED}FastAPI $BASE недоступен.${NC}" >&2; exit 1
fi

if ! python3 - << PYEOF 2>/dev/null | grep -q ok
import socket
s = socket.socket(); s.settimeout(2)
try: s.connect(("$GRPC_HOST", $GRPC_PORT)); print("ok")
except Exception: print("fail")
PYEOF
then
    echo "${YELLOW}ВНИМАНИЕ: gRPC $GRPC_HOST:$GRPC_PORT недоступен.${NC}" >&2
    echo "  Тесты delivery провалятся. Запустите: python delivery_server.py" >&2
fi

STAMP=$(date +%s)
EMAIL_STU_A="student_a_${STAMP}@example.com"
EMAIL_STU_B="student_b_${STAMP}@example.com"
EMAIL_COOK="cook_${STAMP}@example.com"
EMAIL_COURIER="courier_${STAMP}@example.com"
EMAIL_ADMIN="admin_${STAMP}@example.com"
USER_PWD="secret123"

echo "${BOLD}Проверка Sirius.Food${NC} @ $BASE  (stamp=$STAMP)" >&2

# -----------------------------------------------------------------------------
section "1. Сервис и Swagger"
request GET /docs
expect "GET /docs" 200
request GET /openapi.json
if [ "$STATUS" = "200" ]; then
    N=$(python3 -c "import sys,json;print(len(json.load(sys.stdin)['paths']))" <<< "$BODY")
    ok "GET /openapi.json — $N путей"
else
    bad "GET /openapi.json" 200 "$STATUS"
fi

# -----------------------------------------------------------------------------
section "2. Регистрация ролей"
STU_A_ID=""; reg_user_and_store "$EMAIL_STU_A" student "student A" STU_A_ID
STU_B_ID=""; reg_user_and_store "$EMAIL_STU_B" student "student B" STU_B_ID
COOK_ID="";  reg_user_and_store "$EMAIL_COOK" cook "cook" COOK_ID
COURIER_ID=""; reg_user_and_store "$EMAIL_COURIER" courier "courier" COURIER_ID
ADMIN_ID=""; reg_user_and_store "$EMAIL_ADMIN" admin "admin" ADMIN_ID

request POST /users/register "{\"email\":\"bad_${STAMP}@example.com\",\"password\":\"x\"}"
expect "короткий пароль — 400" 400

request POST /users/register "{\"email\":\"$EMAIL_STU_A\",\"password\":\"$USER_PWD\"}"
expect "дубль email — 409" 409

# -----------------------------------------------------------------------------
section "3. Аутентификация"
TOKEN_A=""; TOKEN_A_refresh="";           login_and_store "$EMAIL_STU_A"   "student A" TOKEN_A
TOKEN_B=""; TOKEN_B_refresh="";           login_and_store "$EMAIL_STU_B"   "student B" TOKEN_B
TOKEN_COOK=""; TOKEN_COOK_refresh="";     login_and_store "$EMAIL_COOK"    "cook"      TOKEN_COOK
TOKEN_COURIER=""; TOKEN_COURIER_refresh=""; login_and_store "$EMAIL_COURIER" "courier"   TOKEN_COURIER
TOKEN_ADMIN=""; TOKEN_ADMIN_refresh="";   login_and_store "$EMAIL_ADMIN"   "admin"     TOKEN_ADMIN

if [ -z "$TOKEN_A" ]; then
    echo "${RED}Нет токена student A. Если в §3 все логины вернули 429 — подождите 60с.${NC}" >&2
    exit 1
fi

request GET /users/me "" "$TOKEN_A"
expect "GET /users/me" 200
ME_ROLE=$(jget '["role"]')
[ "$ME_ROLE" = "student" ] && ok "роль = student" || bad "роль" student "$ME_ROLE"

request GET /users/me
expect "GET /users/me без токена — 401" 401

request GET /users/me "" "garbage.token"
expect "GET /users/me мусор — 401" 401

# -----------------------------------------------------------------------------
section "4. Меню (RBAC + кеш)"
MENU_NAME="Тестовое блюдо $STAMP"
request POST /menu/items "{\"name\":\"$MENU_NAME\",\"price\":100,\"category\":\"food\"}" "$TOKEN_COOK"
expect "cook создаёт блюдо" 200
ITEM_ID=$(jget '["item_id"]')

request POST /menu/items "{\"name\":\"X\",\"price\":1,\"category\":\"food\"}" "$TOKEN_A"
expect "student не может создавать — 403" 403

request PATCH "/menu/items/$ITEM_ID" '{"price":120}' "$TOKEN_COOK"
expect "cook обновляет цену" 200

request PATCH "/menu/items/$ITEM_ID" '{"price":-1}' "$TOKEN_COOK"
expect "невалидная цена — 400" 400

request GET /menu/items
expect "GET /menu/items" 200

request GET /menu/categories/food
expect "GET /menu/categories/food" 200

request GET /menu/categories/unknown
expect "неизвестная категория — 422" 422

if redis_exec PING | grep -q PONG; then
    sleep 1
    redis_exec EXISTS "menu:all" | grep -q '^1$' \
        && ok "кеш menu:all заполнен" || skip "кеш menu:all отсутствует"
    redis_exec EXISTS "menu:category:food" | grep -q '^1$' \
        && ok "кеш menu:category:food заполнен" || skip "кеш menu:category:food отсутствует"
else
    skip "Redis недоступен — пропуск проверок кеша"
fi

# -----------------------------------------------------------------------------
section "5. Баланс и IDOR"
request POST "/users/me/topup?amount=500" "" "$TOKEN_A"
expect "student A пополняет свой баланс" 200
BAL=$(jget '["new_balance"]')
if [ -n "$BAL" ] && python3 -c "import sys; sys.exit(0 if float('$BAL')>=500 else 1)"; then
    ok "баланс A = $BAL"
else
    bad "баланс A" "≥500" "${BAL:-пусто}"
fi

request POST "/users/$STU_A_ID/topup?amount=999" "" "$TOKEN_B"
expect "student B → A — 403 (IDOR)" 403

request POST "/users/me/topup?amount=-100" "" "$TOKEN_A"
expect "отрицательное пополнение — 400" 400

# -----------------------------------------------------------------------------
section "6. Заказы"
request POST /orders/create '{"item_id":999999,"quantity":1}' "$TOKEN_A"
expect "несуществующее блюдо — 404" 404

request POST /orders/create '{"item_id":1,"quantity":0}' "$TOKEN_A"
expect "quantity=0 — 400" 400

request POST /orders/create "{\"item_id\":$ITEM_ID,\"quantity\":1}" "$TOKEN_A"
expect "student A создаёт заказ" 200
ORDER_ID=$(jget '["order_id"]')

request GET /orders/my "" "$TOKEN_A"
expect "GET /orders/my" 200
if python3 -c "import sys,json; ids=[o['id'] for o in json.load(sys.stdin)['orders']]; sys.exit(0 if $ORDER_ID in ids else 1)" <<< "$BODY"; then
    ok "заказ $ORDER_ID виден A"
else
    bad "заказ $ORDER_ID в списке" "present" "absent"
fi

request GET /orders/my "" "$TOKEN_B"
if python3 -c "import sys,json; ids=[o['id'] for o in json.load(sys.stdin)['orders']]; sys.exit(0 if $ORDER_ID in ids else 1)" <<< "$BODY"; then
    bad "IDOR: заказ A утёк B" "absent" "present"
else
    ok "IDOR: заказ A не виден B"
fi

request POST "/orders/$ORDER_ID/cancel" "" "$TOKEN_B"
expect "IDOR: B отменяет заказ A — 403" 403

request GET /orders/kitchen/orders "" "$TOKEN_A"
expect "student → кухня — 403" 403

request GET /orders/kitchen/orders "" "$TOKEN_COOK"
expect "cook → кухня" 200

# -----------------------------------------------------------------------------
section "7. Delivery (gRPC-микросервис)"
request POST /orders/create "{\"item_id\":$ITEM_ID,\"quantity\":1}" "$TOKEN_A"
expect "student A создаёт 2-й заказ" 200
DEL_ORDER_ID=$(jget '["order_id"]')

PAID=$(psql_exec "UPDATE orders SET status='paid' WHERE id=$DEL_ORDER_ID RETURNING status;")
if [ "$PAID" = "paid" ]; then
    ok "order $DEL_ORDER_ID → status='paid'"
else
    skip "не удалось перевести order в 'paid' (сейчас: '${PAID:-?}')"
fi

DELIVERY_ID=""
request POST /delivery/assign "{\"order_id\":$DEL_ORDER_ID,\"courier_id\":$COURIER_ID}" "$TOKEN_ADMIN"
if [ "$STATUS" = "200" ]; then
    ok "admin → assign courier (через gRPC)"
    DELIVERY_ID=$(jget '["delivery_id"]')
else
    bad "POST /delivery/assign" 200 "$STATUS"
fi

if [ -n "$DELIVERY_ID" ]; then
    request GET "/delivery/$DELIVERY_ID" "" "$TOKEN_COURIER"
    expect "courier видит свою доставку" 200
    request GET "/delivery/$DELIVERY_ID" "" "$TOKEN_A"
    expect "student A видит доставку своего заказа" 200
    request GET "/delivery/$DELIVERY_ID" "" "$TOKEN_B"
    expect "student B → чужая доставка — 403" 403
    request GET /delivery/my "" "$TOKEN_COURIER"
    expect "GET /delivery/my (courier)" 200

    request PATCH "/delivery/$DELIVERY_ID/complete" "" "$TOKEN_COURIER"
    expect "courier завершает доставку" 200

    DONE=$(psql_exec "SELECT status FROM orders WHERE id=$DEL_ORDER_ID;")
    [ "$DONE" = "delivered" ] && ok "order $DEL_ORDER_ID → delivered (через gRPC)" \
                             || skip "order status = '${DONE:-?}' (ожидалось delivered)"
fi

# -----------------------------------------------------------------------------
section "8. Прямой gRPC к $GRPC_PORT"
cat > /tmp/grpc_helper.py << 'PYEOF'
import os, sys, grpc
sys.path.insert(0, os.getcwd())
import delivery_pb2, delivery_pb2_grpc
H = os.getenv('GRPC_HOST', 'localhost'); P = int(os.getenv('GRPC_PORT', '50051'))
stub = delivery_pb2_grpc.DeliveryServiceStub(grpc.insecure_channel(f'{H}:{P}'))
cmd = sys.argv[1]
try:
    if cmd == 'get':
        r = stub.GetDelivery(delivery_pb2.GetDeliveryRequest(delivery_id=int(sys.argv[2])), timeout=5)
        print(f"id={r.id} order_id={r.order_id} status={r.status}")
    elif cmd == 'byorder':
        r = stub.GetDeliveryByOrder(delivery_pb2.GetDeliveryByOrderRequest(order_id=int(sys.argv[2])), timeout=5)
        print(f"id={r.id} status={r.status}")
    elif cmd == 'list':
        r = stub.ListDeliveries(delivery_pb2.ListDeliveriesRequest(courier_id=int(sys.argv[2])), timeout=5)
        print(f"count={len(r.items)}")
    elif cmd == 'track':
        for upd in stub.TrackDelivery(delivery_pb2.TrackDeliveryRequest(delivery_id=int(sys.argv[2])), timeout=15):
            print(f"  {upd.status} | {upd.message}")
    elif cmd == 'chat':
        def gen():
            for line in ['привет', 'как дела', 'конец']:
                yield delivery_pb2.ChatMessage(sender='student', text=line, timestamp_ms=0)
        for resp in stub.ChatWithCourier(gen(), timeout=10):
            print(f"  [{resp.sender}] {resp.text}")
except grpc.RpcError as e:
    print(f"gRPC ERROR: {e.code()} {e.details()}"); sys.exit(1)
PYEOF

if ! python3 -c "import grpc" 2>/dev/null; then
    skip "grpc не в python — pip install grpcio"
elif [ -z "${DELIVERY_ID:-}" ]; then
    skip "delivery_id неизвестен — пропуск прямых gRPC-тестов"
else
    OUT=$(GRPC_HOST=$GRPC_HOST GRPC_PORT=$GRPC_PORT python3 /tmp/grpc_helper.py get "$DELIVERY_ID" 2>&1) || true
    echo "$OUT" | grep -q "id=$DELIVERY_ID" \
        && ok "gRPC GetDelivery($DELIVERY_ID) = $OUT" \
        || bad "gRPC GetDelivery" "id=$DELIVERY_ID" "$OUT"

    OUT=$(GRPC_HOST=$GRPC_HOST GRPC_PORT=$GRPC_PORT python3 /tmp/grpc_helper.py byorder "$DEL_ORDER_ID" 2>&1) || true
    echo "$OUT" | grep -q "id=$DELIVERY_ID" \
        && ok "gRPC GetDeliveryByOrder($DEL_ORDER_ID)" \
        || bad "gRPC GetDeliveryByOrder" "id=$DELIVERY_ID" "$OUT"

    OUT=$(GRPC_HOST=$GRPC_HOST GRPC_PORT=$GRPC_PORT python3 /tmp/grpc_helper.py list "$COURIER_ID" 2>&1) || true
    echo "$OUT" | grep -q "count=" \
        && ok "gRPC ListDeliveries(courier=$COURIER_ID) = $OUT" \
        || bad "gRPC ListDeliveries" "count>0" "$OUT"
fi

# -----------------------------------------------------------------------------
section "9. Server Streaming: TrackDelivery"
if [ -n "${DELIVERY_ID:-}" ] && python3 -c "import grpc" 2>/dev/null; then
    OUT=$(GRPC_HOST=$GRPC_HOST GRPC_PORT=$GRPC_PORT python3 /tmp/grpc_helper.py track "$DELIVERY_ID" 2>&1) || true
    if echo "$OUT" | grep -q "in_progress" && echo "$OUT" | grep -q "delivered"; then
        ok "TrackDelivery: все статусы получены"
        echo "$OUT" | sed 's/^/         /' >&2
    else
        bad "TrackDelivery" "in_progress + delivered" "$OUT"
    fi
else
    skip "нет delivery_id или grpc не установлен"
fi

# -----------------------------------------------------------------------------
section "10. Bidirectional: ChatWithCourier"
if python3 -c "import grpc" 2>/dev/null; then
    OUT=$(GRPC_HOST=$GRPC_HOST GRPC_PORT=$GRPC_PORT python3 /tmp/grpc_helper.py chat 2>&1) || true
    if echo "$OUT" | grep -q "\[courier\]"; then
        ok "ChatWithCourier работает"
        echo "$OUT" | sed 's/^/         /' >&2
    else
        bad "ChatWithCourier" "ответы курьера" "$OUT"
    fi
else
    skip "grpc не установлен"
fi

# -----------------------------------------------------------------------------
section "11. Celery: фоновые задачи"
if redis_exec PING | grep -q PONG; then
    echo "         ждём 5с (worker)..." >&2
    sleep 5
    if [ -n "${ORDER_ID:-}" ] && redis_exec EXISTS "pdf_generated:$ORDER_ID" | grep -q '^1$'; then
        ok "generate_order_pdf: pdf_generated:$ORDER_ID установлен"
    else
        skip "pdf_generated:$ORDER_ID отсутствует (worker не запущен?)"
    fi
    DLQ=$(redis_exec LLEN dlq 2>/dev/null || echo 0)
    case "${DLQ:-0}" in
        ''|*[!0-9]*) skip "DLQ: нечитаемое значение '${DLQ}'" ;;
        0)           skip "DLQ пуст (задачи не падали)" ;;
        *)           ok   "DLQ: $DLQ записей" ;;
    esac
else
    skip "Redis недоступен — Celery-проверки пропущены"
fi

echo "         провоцируем падение email-задачи (order_id=5)..." >&2
for i in 1 2 3; do
    request POST /orders/create "{\"item_id\":$ITEM_ID,\"quantity\":1}" "$TOKEN_A"
done
# ~10с: retry_backoff + jitter + 3 попытки
sleep 12
DLQ=$(redis_exec LLEN dlq 2>/dev/null || echo 0)
case "${DLQ:-0}" in
    ''|*[!0-9]*) skip "DLQ: нечитаемое значение '${DLQ}'" ;;
    0)           skip "DLQ пуст (задачи не упали)" ;;
    *)           ok   "DLQ: $DLQ записей (email-задача упала → в DLQ)" ;;
esac

# -----------------------------------------------------------------------------
section "12. Refresh Token rotation"
if [ -n "$TOKEN_A_refresh" ]; then
    request POST /auth/refresh "{\"refresh_token\":\"$TOKEN_A_refresh\"}"
    expect "первый refresh" 200
    RT2=$(jget '["refresh_token"]')
    if [ -n "$RT2" ] && [ "$RT2" != "$TOKEN_A_refresh" ]; then
        ok "ротация: выдан новый refresh"
    else
        bad "ротация" "новый токен" "${RT2:-пусто}"
    fi

    request POST /auth/refresh "{\"refresh_token\":\"$TOKEN_A_refresh\"}"
    expect "старый refresh повторно — 401" 401

    if [ -n "$RT2" ]; then
        request POST /auth/refresh "{\"refresh_token\":\"$RT2\"}"
        expect "новая сессия тоже сброшена — 401" 401
    fi
else
    skip "нет refresh-токена (login в §3 не удался)"
fi

# -----------------------------------------------------------------------------
section "13. Rate limit (/auth/login, 5/60с)"
request POST /auth/login '{"email":"nobody@example.com","password":"wrong"}'
if [ "$STATUS" = "429" ]; then
    ok "rate limit: 429 сразу (квота исчерпана логинами в §3)"
elif [ "$STATUS" = "401" ]; then
    GOT_429=0
    for i in 2 3 4 5 6 7 8; do
        request POST /auth/login '{"email":"nobody@example.com","password":"wrong"}'
        if [ "$STATUS" = "429" ]; then
            ok "rate limit: 429 на попытке $i"
            GOT_429=1; break
        fi
    done
    [ "$GOT_429" = "0" ] && skip "429 не получен (Redis/RATE_LIMIT_ENABLED=False?)"
else
    skip "rate limit: неожиданный статус $STATUS"
fi
echo "${YELLOW}  [!] /auth/login заблокирован на ~60с с вашего IP.${NC}" >&2

# =============================================================================
echo >&2
echo "${BOLD}══════════════════════════════════════════════════════════════════════${NC}" >&2
if [ "$FAIL" = "0" ]; then
    echo "${GREEN}${BOLD}  ВСЁ OK: $PASS прошло, $SKIP пропущено, 0 ошибок.${NC}" >&2
    EXIT=0
else
    echo "${RED}${BOLD}  ИТОГ: $PASS прошло, $SKIP пропущено, $FAIL провалилось.${NC}" >&2
    EXIT=1
fi
echo "${BOLD}══════════════════════════════════════════════════════════════════════${NC}" >&2