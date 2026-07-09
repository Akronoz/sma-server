#!/usr/bin/env bash
# Enqueue a test ON/OFF command.
# Usage: bash scripts/test_command.sh ESP-ACA704305E20 1 true
set -euo pipefail
cd "$(dirname "$0")/.."

DEVICE="${1:-}"
OUTPUT="${2:-1}"
STATE="${3:-true}"

if [[ -f .env ]]; then set -a; source .env; set +a; fi
API="${SMA_API_KEY:-}"
URL="${TEST_API_URL:-http://10.8.0.1:8000}"

if [[ -z "$DEVICE" || -z "$API" ]]; then
  echo "Usage: bash scripts/test_command.sh ESP-XXXXXXXXXXXX [output 1-4] [true|false]"
  exit 1
fi

echo "POST $URL/api/v1/iot/commands"
curl -sS -X POST "$URL/api/v1/iot/commands" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API" \
  -d "{\"device_id\":\"$DEVICE\",\"action\":\"set_output\",\"output\":$OUTPUT,\"state\":$STATE}"
echo ""
echo ""
echo "Pending queue (should drain in ~1s if iot-gateway on the RPi is active):"
sleep 2
curl -sS -H "X-API-Key: $API" "$URL/api/v1/iot/commands/pending"
echo ""