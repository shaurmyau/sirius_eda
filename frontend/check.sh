#!/usr/bin/env bash
# Объективные проверки SSR-витрины «Сириус.Еды».
# Берёт первое блюдо из REST API и ищет его название в HTML страниц фронтенда.
#
# Запуск из папки frontend (бэкенд и `npm run dev` / `npm start` уже запущены):
#   chmod +x check.sh && ./check.sh
#
# Переопределить адреса: FRONT_URL=... API_URL=... ./check.sh

set -u

FRONT="${FRONT_URL:-http://localhost:3000}"
API="${API_URL:-http://127.0.0.1:8000}"

pass=0
fail=0

report() {
  if [ "$1" -eq 0 ]; then
    echo "PASS  $2"
    pass=$((pass + 1))
  else
    echo "FAIL  $2"
    fail=$((fail + 1))
  fi
}

# Первое блюдо из API: id и название (дизайн-независимый маркер SSR).
# Бэкенд отдаёт { "status": "success", "items": [...] }; «голый» массив тоже ок.
read -r FIRST_ID FIRST_NAME <<EOF
$(curl -s "$API/menu/items" | python3 -c 'import sys, json
d = json.load(sys.stdin)
items = d.get("items") if isinstance(d, dict) else d
if isinstance(items, list) and items:
    print(items[0]["id"], items[0]["name"])
else:
    print("", "")' 2>/dev/null)
EOF

if [ -z "${FIRST_NAME:-}" ]; then
  echo "FAIL  REST API $API/menu/items не вернул список блюд (запустите: python seed.py)"
  echo
  echo "Итог: PASS=0 FAIL=1"
  exit 1
fi

echo "Маркер: блюдо #$FIRST_ID «$FIRST_NAME»"
echo

# 1. API отвечает списком.
curl -sf "$API/menu/items" >/dev/null 2>&1
report $? "API: GET $API/menu/items отвечает"

# 2. API отдаёт одно блюдо.
curl -sf "$API/menu/items/$FIRST_ID" >/dev/null 2>&1
report $? "API: GET $API/menu/items/$FIRST_ID отвечает"

# 3. API возвращает 404 для несуществующего блюда.
code=$(curl -s -o /dev/null -w '%{http_code}' "$API/menu/items/999999")
[ "$code" = "404" ]
report $? "API: несуществующее блюдо -> 404 (получено: $code)"

# 4. SSR: блюдо есть в HTML /menu.
MENU_HTML=$(curl -s "$FRONT/menu")
printf '%s' "$MENU_HTML" | grep -qF "$FIRST_NAME"
report $? "SSR: «$FIRST_NAME» присутствует в HTML /menu (Ctrl+U)"

# 5. SSR: блюдо есть в HTML карточки /menu/<id>.
ITEM_HTML=$(curl -s "$FRONT/menu/$FIRST_ID")
printf '%s' "$ITEM_HTML" | grep -qF "$FIRST_NAME"
report $? "SSR: «$FIRST_NAME» присутствует в HTML /menu/$FIRST_ID"

# 6. Метатеги карточки (9 баллов): title, description, Open Graph.
printf '%s' "$ITEM_HTML" | grep -qE '<title>[^<]*'"$FIRST_NAME"
report $? "SEO: <title> содержит название блюда"
printf '%s' "$ITEM_HTML" | grep -qE '<meta name="description"'
report $? "SEO: есть <meta name=\"description\">"
printf '%s' "$ITEM_HTML" | grep -qE '<meta property="og:title"'
report $? "SEO: есть <meta property=\"og:title\">"

# 7. Несуществующее блюдо -> 404 ИЛИ (при потоковой отдаче со loading.tsx)
#    статус 200 с мета-тегом noindex: Next.js уже отправил заголовки до notFound().
NF_HEADERS=$(mktemp)
NF_BODY=$(curl -s -D "$NF_HEADERS" "$FRONT/menu/999999")
nf_code=$(head -1 "$NF_HEADERS" | awk '{print $2}')
rm -f "$NF_HEADERS"
if [ "$nf_code" = "404" ] || printf '%s' "$NF_BODY" | grep -qE 'name="robots" content="noindex'; then
  report 0 "Фронтенд: /menu/999999 -> not found (HTTP $nf_code)"
else
  report 1 "Фронтенд: /menu/999999 должен давать 404/noindex (HTTP $nf_code)"
fi

# 8. (10 баллов) CSR-страница не содержит блюд в HTML.
if curl -sf -o /dev/null "$FRONT/menu-csr" 2>/dev/null; then
  if curl -s "$FRONT/menu-csr" | grep -qF "$FIRST_NAME"; then
    report 1 "CSR: в HTML /menu-csr не должно быть блюд (они есть)"
  else
    report 0 "CSR: в HTML /menu-csr нет блюд (данные грузит браузер)"
  fi
else
  echo "SKIP  /menu-csr недоступна"
fi

echo
echo "Итог: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
