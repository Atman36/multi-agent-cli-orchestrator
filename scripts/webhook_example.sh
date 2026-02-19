#!/usr/bin/env bash
set -euo pipefail

TOKEN="${WEBHOOK_TOKEN:-dev-token}"
PAYLOAD="examples/webhook_payloads/simple.json"

curl -sS -X POST "http://127.0.0.1:8080/webhook"   -H "Content-Type: application/json"   -H "Authorization: Bearer ${TOKEN}"   -d @"${PAYLOAD}" | jq .
