#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${LOCUST_HOST:-http://127.0.0.1:8000}"
DURATION="${LOCUST_DURATION:-60s}"
SPAWN_RATE="${LOCUST_SPAWN_RATE:-10}"
STAGES="${LOCUST_STAGES:-50 100 200}"
REPORT_DIR="${LOCUST_REPORT_DIR:-reports/locust}"

command -v locust >/dev/null 2>&1 || {
  echo "Locust is not installed. Run: pip install -r requirements.txt" >&2
  exit 1
}
mkdir -p "$REPORT_DIR"

echo "Target: $HOST | duration per stage: $DURATION | stages: $STAGES"
echo "For authenticated order traffic set LOCUST_TOKEN and LOCUST_ITEM_ID."

for users in $STAGES; do
  prefix="$REPORT_DIR/users-$users"
  echo
  echo "=== Locust: $users users, spawn rate $SPAWN_RATE/s ==="
  locust -f locustfile.py \
    --headless \
    --host "$HOST" \
    --users "$users" \
    --spawn-rate "$SPAWN_RATE" \
    --run-time "$DURATION" \
    --stop-timeout 10 \
    --csv "$prefix" \
    --csv-full-history \
    --html "$prefix.html"
done

echo
echo "Reports saved to: $REPORT_DIR"
echo "Review *_stats.csv for RPS/failure/latency and *_stats_history.csv for trends."
