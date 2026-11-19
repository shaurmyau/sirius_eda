#!/usr/bin/env bash
# =============================================================================
# test.sh — сквозная проверка Sirius.Food API (Лабораторная работа № 3).
#
# Запуск:
#   1) в одном терминале:  REPO_BACKEND=memory uvicorn app.main:app --reload
#   2) в другом:           ./test.sh
#      или с другим адресом: BASE=http://host:8000 ./test.sh
#
# Зависимости: bash, curl, python3 (для разбора JSON).
# jq — не требуется.
# =============================================================================
set -u

BASE="${BASE:-http://127.0.0.1:8000}"

# --- цвета и счётчики --------------------------------------------------------
PASS=0
FAIL=0
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'

section() { echo; echo "${CYAN}${BOLD}==== $1 ====${NC}"; }

ok()  { echo "${GREEN}  [PASS]${NC} $1"; PASS=$((PASS+1)); }

bad() {
  echo "${RED}  [FAIL]${NC} $1 — ожидалось ${BOLD}$2${NC}, получено ${BOLD}$3${NC}"
  if [ -n "${BODY:-}" ] && [ "${BODY:-}" != "" ]; then
    echo "         тело ответа: $BODY"
  fi
  FAIL=$((FAIL+1))
}

# --- обёртка над curl --------------------------------------------------------
# Пишет тело в $BODY, код в $STATUS.
# Использование: request METHOD PATH [JSON_DATA] [BEARER_TOKEN]
request() {
  local method="$1" path="$2" data="${3:-}" token="${4:-}"
  local args=(-s -o /tmp/_body -w '%{http_code}' -X "$method" "$BASE$path"
              -H 'Content-Type: application/json')
  [ -n "$data" ]  && args+=(-d "$data")
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  STATUS=$(curl "${args[@]}" 2>/dev/null || echo "000")
  BODY=$(cat /tmp/_body 2>/dev/null || echo "")
}

# jget '["access_token"]'   — вытащить поле из $BODY
jget() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)" <<< "$BODY" 2>/dev/null; }

# Проверка кода ответа
expect() {
  local name="$1" want="$2"
  if [ "$STATUS" = "$want" ]; then ok "$name [$STATUS]"; else bad "$name" "$want" "$STATUS"; fi
}

# =============================================================================
#   ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА
# =============================================================================
if ! curl -s --max-time 3 "$BASE/docs" -o /dev/null; then
  echo "${RED}Сервер $BASE недоступен.${NC}"
  echo "Запусти в другом терминале:"
  echo "   uvicorn app.main:app --reload"
  exit 1
fi

STAMP=$(date +%s)
EMAIL_A="studentA_${STAMP}@sirius.ru"
EMAIL_B="studentB_${STAMP}@sirius.ru"
PWD="secret123"

echo "${BOLD}Проверка API Sirius.Food по адресу $BASE${NC}"
echo "Метка запуска: $STAMP (email-адреса уникальны для каждого запуска)"

# =============================================================================
section "0. Сервис и Swagger"
request GET /docs
if [ "$STATUS" = "200" ]; then ok "GET /docs — 200 (Swagger доступен)"; 
else                          bad "GET /docs" 200 "$STATUS"; fi

# =============================================================================
section "1. Регистрация и валидация пароля"
request POST /users/register "{\"email\":\"$EMAIL_A\",\"password\":\"$PWD\",\"phone\":\"1234567890\"}"
expect "регистрация студента A — 200" 200
USER_A_ID=$(jget '["user_id"]')
echo "         user_id студента A = $USER_A_ID"

request POST /users/register "{\"email\":\"$EMAIL_A\",\"password\":\"$PWD\"}"
expect "повторная регистрация — 409 Conflict" 409

request POST /users/register "{\"email\":\"short_${STAMP}@sirius.ru\",\"password\":\"x\"}"
expect "короткий пароль — 400 Bad Request" 400

# =============================================================================
section "2. Аутентификация и JWT"
request POST /auth/login "{\"email\":\"$EMAIL_A\",\"password\":\"WRONG\"}"
expect "неверный пароль — 401" 401

request POST /auth/login "{\"email\":\"$EMAIL_A\",\"password\":\"$PWD\"}"
expect "корректный логин — 200" 200
TOKEN_A=$(jget '["access_token"]')
REFRESH_A=$(jget '["refresh_token"]')
if [ -n "$TOKEN_A" ]; then ok "получен access_token (len=${#TOKEN_A})";
else                     bad "access_token присутствует" "непусто" "пусто"; fi

request GET /users/me "" "$TOKEN_A"
expect "GET /users/me с токеном — 200" 200
ME_EMAIL=$(jget '["email"]')
[ "$ME_EMAIL" = "$EMAIL_A" ] && ok "email в /users/me совпадает" \
                             || bad "/users/me.email" "$EMAIL_A" "$ME_EMAIL"
ME_ROLE=$(jget '["role"]')
[ "$ME_ROLE" = "student" ] && ok "роль по умолчанию — student" \
                           || bad "роль студента" "student" "$ME_ROLE"

request GET /users/me
expect "GET /users/me без токена — 401" 401

request GET /users/me "" "garbage.jwt.token"
expect "GET /users/me с мусорным токеном — 401" 401

# =============================================================================
section "3. IDOR на /users/{id}/topup"
request POST "/users/me/topup?amount=100" "" "$TOKEN_A"
expect "пополнение своего баланса — 200" 200
NEW_BAL=$(jget '["new_balance"]')
[ "$NEW_BAL" = "100.0" ] && ok "баланс после пополнения — 100.0" \
                         || bad "баланс студента A" "100.0" "$NEW_BAL"

# Второй студент
request POST /users/register "{\"email\":\"$EMAIL_B\",\"password\":\"$PWD\"}"
USER_B_ID=$(jget '["user_id"]')
request POST /auth/login "{\"email\":\"$EMAIL_B\",\"password\":\"$PWD\"}"
TOKEN_B=$(jget '["access_token"]')
[ -n "$TOKEN_B" ] && ok "второй студент зарегистрирован и залогинен" \
                  || bad "логин студента B" "access_token" "пусто"

# B пытается пополнить баланс A
request POST "/users/$USER_A_ID/topup?amount=999" "" "$TOKEN_B"
expect "чужой баланс — 403 (IDOR закрыт)" 403

# =============================================================================
section "4. RBAC — student НЕ имеет доступа к кухне / меню / доставке"
request POST /menu/items '{"name":"Борщ","price":30}' "$TOKEN_A"
expect "POST /menu/items (роль cook) — 403" 403

request GET /orders/kitchen/orders "" "$TOKEN_A"
expect "GET /orders/kitchen/orders (роль cook) — 403" 403

request POST /delivery/assign '{"order_id":1,"courier_id":1}' "$TOKEN_A"
expect "POST /delivery/assign (роль admin) — 403" 403

# =============================================================================
section "5. Валидация и бизнес-правила заказов"
request POST /orders/create '{"item_id":1,"quantity":0}' "$TOKEN_A"
expect "quantity=0 — 400" 400

request POST /orders/create '{"item_id":999,"quantity":1}' "$TOKEN_A"
expect "несуществующее блюдо — 404" 404

request POST /orders/create '{"item_id":1,"quantity":1}'
expect "заказ без токена — 401" 401

# =============================================================================
section "6. Refresh Token rotation"
request POST /auth/refresh "{\"refresh_token\":\"$REFRESH_A\"}"
expect "первый refresh — 200" 200
NEW_REFRESH=$(jget '["refresh_token"]')
[ -n "$NEW_REFRESH" ] && [ "$NEW_REFRESH" != "$REFRESH_A" ] \
  && ok "refresh выдан новый (ротация работает)" \
  || bad "ротация refresh" "новый токен" "старый/пусто"

request POST /auth/refresh "{\"refresh_token\":\"$REFRESH_A\"}"
expect "повторное использование старого refresh — 401" 401

request POST /auth/refresh "{\"refresh_token\":\"$NEW_REFRESH\"}"
expect "новый refresh тоже сброшен (all sessions revoked) — 401" 401

# =============================================================================
section "7. Rate limiting на /auth/login (5 запросов / 60 секунд)"
echo "         (если Redis не запущен или RATE_LIMIT_ENABLED=False — тест пропустится)"
GOT_429=0
for i in $(seq 1 12); do
  request POST /auth/login '{"email":"nobody@x.ru","password":"wrong"}'
  if [ "$STATUS" = "429" ]; then
    echo "         итерация $i: получен 429"
    GOT_429=1
    break
  fi
done
if [ "$GOT_429" = "1" ]; then
  ok "rate limit сработал (429)"
else
  echo "${YELLOW}  [SKIP]${NC} rate limit не сработал — вероятно, Redis выключен или RATE_LIMIT_ENABLED=False"
fi
echo "${YELLOW}  [!] После этого теста /auth/login заблокирован на ~60 секунд с вашего IP.${NC}"

# =============================================================================
echo
echo "${BOLD}══════════════════════════════════════════════════════════════════${NC}"
if [ "$FAIL" = "0" ]; then
  echo "${GREEN}${BOLD}  ВСЁ ОК: $PASS тестов прошли, ошибок нет.${NC}"
  EXIT=0
else
  echo "${RED}${BOLD}  ИТОГ: $PASS успешно, $FAIL с ошибками.${NC}"
  EXIT=1
fi
echo "${BOLD}══════════════════════════════════════════════════════════════════${NC}"
exit $EXIT