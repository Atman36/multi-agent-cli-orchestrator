#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d ".venv" ]]; then
  echo "ERROR: .venv not found. Run: make venv && source .venv/bin/activate && make install"
  exit 1
fi

# Load env if present
set -a
if [[ -f ".env" ]]; then source .env; fi
set +a

cleanup() {
  echo
  echo "Stopping..."
  [[ -n "${API_PID:-}" ]] && kill "${API_PID}" 2>/dev/null || true
  [[ -n "${SCHED_PID:-}" ]] && kill "${SCHED_PID}" 2>/dev/null || true
  [[ -n "${RUNNER_PID:-}" ]] && kill "${RUNNER_PID}" 2>/dev/null || true
  wait || true
}
trap cleanup EXIT INT TERM

echo "Starting webhook API..."
.venv/bin/python -m gateway.webhook_server &
API_PID=$!

sleep 0.5
echo "Starting scheduler..."
.venv/bin/python -m orchestrator.scheduler &
SCHED_PID=$!

sleep 0.5
echo "Starting runner..."
.venv/bin/python -m orchestrator.runner &
RUNNER_PID=$!

echo
echo "Running. API: http://127.0.0.1:8080"
echo "Press Ctrl+C to stop."
wait
