#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: ./scripts/check_practical_work_10.sh [all|fast|integration|contract|mutation|load]

  fast         Unit/API tests and Pact contract (no Docker required)
  integration  PostgreSQL + RabbitMQ Testcontainers integration tests
  contract     Pact consumer and provider verification only
  mutation     mutmut run + mutmut results for OrderService
  load         staged Locust run (API must already be running)
  all          fast + integration + mutation
EOF
}

mode="${1:-all}"
case "$mode" in
  fast)
    pytest -m "not integration" -v
    ;;
  integration)
    pytest tests/integration -m integration -v
    ;;
  contract)
    pytest tests/contracts -m contract -v
    ;;
  mutation)
    pytest tests/unit -v
    mutmut run
    mutmut results
    ;;
  load)
    exec bash ./scripts/run_load_test.sh
    ;;
  all)
    pytest -m "not integration" -v
    pytest tests/integration -m integration -v
    pytest tests/unit -v
    mutmut run
    mutmut results
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
