#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

USERS=${USERS:-300}
SPAWN=${SPAWN:-30}
DURATION=${DURATION:-60s}
WORKERS=${WORKERS:-2}
ITEMS=${ITEMS:-1500}
PORT=${PORT:-8000}
OUT=lab4_results

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'

dc() { if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi; }

wait_http() {
    local url=$1 tries=${2:-40}
    for _ in $(seq 1 "$tries"); do
        curl -s -o /dev/null --max-time 1 "$url" && return 0
        sleep 1
    done
    return 1
}

UVICORN_PID=""
cleanup() {
    if [ -n "$UVICORN_PID" ]; then
        kill "$UVICORN_PID" 2>/dev/null || true
        for _ in $(seq 1 30); do kill -0 "$UVICORN_PID" 2>/dev/null || break; sleep 0.1; done
        kill -9 "$UVICORN_PID" 2>/dev/null || true
        UVICORN_PID=""
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti:"$PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

mkdir -p "$OUT"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

# ─── locustfile с настраиваемым темпом ───
cat > locustfile.py << 'EOF'
import os
from locust import HttpUser, task, between

WAIT_MIN = float(os.getenv("WAIT_MIN", "0.05"))
WAIT_MAX = float(os.getenv("WAIT_MAX", "0.15"))

class MenuUser(HttpUser):
    wait_time = between(WAIT_MIN, WAIT_MAX)

    @task(3)
    def get_all_menu(self):
        self.client.get("/menu/items")

    @task(1)
    def get_category(self):
        self.client.get("/menu/categories/food")
EOF
export WAIT_MIN=${WAIT_MIN:-0.05} WAIT_MAX=${WAIT_MAX:-0.15}

echo "${CYAN}${BOLD}Lab 4 — измерения Cache-Aside${NC}"
echo "  workers=$WORKERS users=$USERS spawn=$SPAWN duration=$DURATION items=$ITEMS"

# ─── БД ───
echo "==> docker db up"
dc up -d db >/dev/null
for _ in $(seq 1 30); do
    dc exec -T db pg_isready -U sirius -d sirius_food >/dev/null 2>&1 && break
    sleep 1
done

# ─── Сид ───
echo "==> seed menu ($ITEMS rows)"
dc exec -T db psql -U sirius -d sirius_food -c "TRUNCATE menu_items RESTART IDENTITY CASCADE;" >/dev/null
dc exec -T db psql -U sirius -d sirius_food -c "
INSERT INTO menu_items (name, price, is_available, category)
SELECT
  CASE g % 3 WHEN 0 THEN 'Блюдо ' || g WHEN 1 THEN 'Напиток ' || g ELSE 'Прочее ' || g END,
  ROUND((50 + random() * 950)::numeric, 2)::float8,
  true,
  CASE g % 3 WHEN 0 THEN 'food' WHEN 1 THEN 'drink' ELSE 'other' END
FROM generate_series(1, $ITEMS) AS g;
" >/dev/null
dc exec -T db psql -U sirius -d sirius_food -c "ANALYZE menu_items;" >/dev/null
echo "   $(dc exec -T db psql -U sirius -d sirius_food -tAc 'SELECT count(*) FROM menu_items;' | tr -d '[:space:]') rows"

# ─── Сценарий ───
run_scenario() {
    local name=$1 desc=$2
    echo
    echo "${CYAN}${BOLD}=== $desc ===${NC}"

    uvicorn app.main:app --port "$PORT" --workers "$WORKERS" --log-level warning \
        > "$OUT/${name}_uvicorn.log" 2>&1 &
    UVICORN_PID=$!

    if ! wait_http "http://127.0.0.1:$PORT/docs"; then
        echo "${RED}uvicorn не стартовал — см. $OUT/${name}_uvicorn.log${NC}"
        tail -30 "$OUT/${name}_uvicorn.log"
        exit 1
    fi
    sleep 1

    echo "   single-request timings (curl, последовательно):"
    for i in 1 2 3 4 5; do
        curl -s -o /dev/null -w "     #$i: %{http_code}  %{time_total}s\n" \
             "http://127.0.0.1:$PORT/menu/items"
    done

    echo "   locust ($USERS users, ${DURATION})..."
    locust -f locustfile.py --host="http://127.0.0.1:$PORT" \
        --headless -u "$USERS" -r "$SPAWN" -t "$DURATION" \
        --csv="$OUT/$name" --only-summary 2>&1 | tee "$OUT/${name}_locust.txt"

    kill "$UVICORN_PID" 2>/dev/null || true
    for _ in $(seq 1 30); do kill -0 "$UVICORN_PID" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$UVICORN_PID" 2>/dev/null || true
    UVICORN_PID=""
    sleep 2
}

# ─── BASELINE ───
echo "==> redis STOP (baseline)"
dc stop redis >/dev/null 2>&1 || true
sleep 1
run_scenario baseline "BASELINE — Redis выключен, всё идёт в PostgreSQL"

# ─── CACHED ───
echo "==> redis START (cached)"
dc start redis >/dev/null
sleep 2
dc exec -T redis redis-cli FLUSHALL >/dev/null 2>&1 || true
run_scenario cached "CACHED — Redis включён, Cache-Aside"

echo
echo "==> Redis keys после cached:"
dc exec -T redis redis-cli --scan --pattern 'menu:*' 2>/dev/null | sed 's/^/     /' || echo "     (none)"

# ─── Сводка ───
python3 << 'PYEOF'
import csv
from pathlib import Path

OUT = Path("lab4_results")

def read(name):
    with open(OUT / f"{name}_stats.csv") as f:
        rows = list(csv.DictReader(f))
    agg = next((r for r in rows if r.get("Name") == "Aggregated"),
               rows[-1] if rows else None)
    if not agg:
        return None
    def f(k):
        try: return float(agg.get(k) or 0)
        except: return 0.0
    def i(k):
        try: return int(float(agg.get(k) or 0))
        except: return 0
    return {
        "rps": f("Requests/s"), "avg": f("Average Response Time"),
        "p50": f("50%"), "p95": f("95%"), "p99": f("99%"),
        "count": i("Request Count"), "fail": i("Failure Count"),
    }

b = read("baseline")
c = read("cached")
if not b or not c:
    raise SystemExit("missing stats")

def rr(x, y):
    return f"{y/x:.2f}x" if x and y else "—"

print()
print("=" * 80)
print(f"  {'Метрика':<28}{'Без кеша':>14}{'С кешем':>14}{'Ускорение':>16}")
print("-" * 80)
print(f"  {'RPS':<28}{b['rps']:>14.1f}{c['rps']:>14.1f}{rr(b['rps'], c['rps']):>16}")
print(f"  {'Avg latency (ms)':<28}{b['avg']:>14.1f}{c['avg']:>14.1f}{rr(b['avg'], c['avg']):>16}")
print(f"  {'P50 latency (ms)':<28}{b['p50']:>14.1f}{c['p50']:>14.1f}{rr(b['p50'], c['p50']):>16}")
print(f"  {'P95 latency (ms)':<28}{b['p95']:>14.1f}{c['p95']:>14.1f}{rr(b['p95'], c['p95']):>16}")
print(f"  {'P99 latency (ms)':<28}{b['p99']:>14.1f}{c['p99']:>14.1f}{rr(b['p99'], c['p99']):>16}")
print(f"  {'Всего запросов':<28}{b['count']:>14d}{c['count']:>14d}{rr(b['count'], c['count']):>16}")
print(f"  {'Ошибок':<28}{b['fail']:>14d}{c['fail']:>14d}")
print("=" * 80)
print(f"\n  CSV: {OUT}/baseline_stats.csv {OUT}/cached_stats.csv")
PYEOF