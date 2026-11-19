#!/usr/bin/env bash
# Грубые замеры curl для SSR и CSR (дополнение к замерам в Chrome DevTools).
# curl НЕ выполняет JavaScript: для /menu-csr он покажет время получения только
# каркаса без блюд — это и есть наглядная разница с SSR.
#
#   ./measure.sh            # 3 замера на страницу
#   RUNS=5 ./measure.sh

set -u
FRONT="${FRONT_URL:-http://localhost:3000}"
RUNS="${RUNS:-3}"

for path in /menu /menu-csr; do
  echo "== $path"
  for i in $(seq 1 "$RUNS"); do
    curl -s -o /dev/null -H 'Cache-Control: no-cache' \
      -w "  замер $i: TTFB=%{time_starttransfer}s  total=%{time_total}s  размер=%{size_download}B\n" \
      "$FRONT$path"
  done
done
