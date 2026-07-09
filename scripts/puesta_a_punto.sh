#!/usr/bin/env bash
# Diagnose and verify the IoT -> Influx pipeline (run on the VPS).
set -euo pipefail

cd "$(dirname "$0")/.."
API_KEY="${SMA_API_KEY:-}"
WG_NAME="${WG_CONTAINER:-wg-easy}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  API_KEY="${SMA_API_KEY:-}"
  WG_NAME="${WG_CONTAINER:-wg-easy}"
fi

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  SETUP CHECK — backend + Influx IoT                    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

echo "── 1. WireGuard (wg-easy) ──"
docker ps --format '  {{.Names}}  {{.Status}}' | grep -i wg || echo "  No wg container found!"
if docker ps --format '{{.Names}}' | grep -qx "$WG_NAME"; then
  echo "  OK: $WG_NAME running"
else
  echo "  ERROR: missing '$WG_NAME'. Set WG_CONTAINER in .env"
fi

echo ""
echo "── 2. backend ──"
if docker ps --format '{{.Names}}' | grep -qx backend; then
  docker ps --filter name=backend --format '  {{.Names}}  {{.Status}}  ports={{.Ports}}'
  echo "  NetworkMode=$(docker inspect backend --format '{{.HostConfig.NetworkMode}}')"
else
  echo "  ERROR: backend is not running"
fi

echo ""
echo "── 3. API over VPN (10.8.0.1:8000) — used by the RPi ──"
if curl -sf http://10.8.0.1:8000/health >/dev/null; then
  curl -s http://10.8.0.1:8000/health
  echo ""
  echo "  OK health"
else
  echo "  FAILED — the RPi cannot send telemetry"
  echo "  Fix: bash deploy/up.sh"
fi

echo ""
echo "── 4. Influx variables in the container ──"
docker inspect backend --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep -E '^INFLUX_|^SMA_API_KEY' \
  | while IFS= read -r line; do
      k="${line%%=*}"
      v="${line#*=}"
      if [[ "$k" == *TOKEN* || "$k" == *KEY* ]]; then
        echo "  $k=${v:0:4}… (len ${#v})"
      else
        echo "  $line"
      fi
    done || echo "  (no container)"

echo ""
echo "── 5. temperature_1 points in Influx (24h) ──"
if [[ -f scripts/check_iot_influx.sh ]]; then
  bash scripts/check_iot_influx.sh 2>/dev/null | tail -20 || true
fi

echo ""
echo "── 6. IoT write test (optional) ──"
if [[ -n "$API_KEY" ]] && curl -sf http://10.8.0.1:8000/health >/dev/null; then
  HTTP=$(curl -s -o /tmp/iot-test.json -w "%{http_code}" \
    -X POST http://10.8.0.1:8000/api/v1/iot/telemetry \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d '{"events":[{"device_id":"TEST-PING","metric":"temperature_1","channel":"1","value":42.0,"received_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}]}')
  echo "  POST test telemetry -> HTTP $HTTP  $(cat /tmp/iot-test.json 2>/dev/null)"
else
  echo "  Skipped (SMA_API_KEY missing in environment or API down)"
fi

echo ""
echo "══════════════════════════════════════════════════════════"
echo "INFLUX DATA EXPLORER — temperature chart"
echo "══════════════════════════════════════════════════════════"
echo "  Bucket:      sma"
echo "  Measurement: iot_telemetry"
echo "  Field:       value"
echo "  Tag metric:  temperature_1"
echo "  Tag device:  ESP-ACA704305E20  (your serial)"
echo "  Range:       Last 1 hour (or 6 hours)"
echo ""
echo "Flux (paste in Script Editor):"
cat <<'FLUX'

from(bucket: "sma")
  |> range(start: -6h)
  |> filter(fn: (r) => r._measurement == "iot_telemetry")
  |> filter(fn: (r) => r._field == "value")
  |> filter(fn: (r) => r.metric == "temperature_1")
  |> filter(fn: (r) => r.device_id == "ESP-ACA704305E20")
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)

FLUX
echo ""
echo "If count() = 1 -> almost no telemetry arriving from the RPi."
echo "If count() > 50 -> you should see a curve (Visualization: Graph)."
echo "══════════════════════════════════════════════════════════"