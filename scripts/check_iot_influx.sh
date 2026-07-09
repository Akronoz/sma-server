#!/usr/bin/env bash
# Check whether IoT telemetry exists in InfluxDB (temperature, inputs).
# Usage on the VPS:
#   cd ~/gironasa/backend && bash scripts/check_iot_influx.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

ORG="${INFLUX_ORG:-Gironasa}"
BUCKET="${INFLUX_BUCKET:-sma}"
URL="${INFLUX_URL:-http://127.0.0.1:8086}"
TOKEN="${INFLUX_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: INFLUX_TOKEN missing in .env"
  exit 1
fi

echo "=== IoT telemetry in Influx ==="
echo "Org: $ORG  Bucket: $BUCKET  URL: $URL"
echo ""

FLUX='
from(bucket: "'"$BUCKET"'")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "iot_telemetry")
  |> filter(fn: (r) => r._field == "value")
  |> group(columns: ["device_id", "metric"])
  |> count()
  |> sort(columns: ["_value"], desc: true)
'

echo "--- Points per device and metric (last 24h) ---"
curl -sS -X POST "$URL/api/v2/query?org=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ORG'))")" \
  -H "Authorization: Token $TOKEN" \
  -H "Accept: application/csv" \
  -H "Content-type: application/vnd.flux" \
  --data-binary "$FLUX" | head -40

echo ""
echo "--- Last 5 temperature_1 readings ---"
FLUX2='
from(bucket: "'"$BUCKET"'")
  |> range(start: -6h)
  |> filter(fn: (r) => r._measurement == "iot_telemetry")
  |> filter(fn: (r) => r._field == "value")
  |> filter(fn: (r) => r.metric == "temperature_1")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 5)
'

curl -sS -X POST "$URL/api/v2/query?org=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ORG'))")" \
  -H "Authorization: Token $TOKEN" \
  -H "Accept: application/csv" \
  -H "Content-type: application/vnd.flux" \
  --data-binary "$FLUX2"

echo ""
echo "If there are no rows: the gateway is not reaching the backend or the ESP is not publishing MQTT."
echo "If there are 1-2 points: it just started; wait a few minutes with the gateway OK."
echo ""
echo "In the Influx Data Explorer UI:"
echo "  measurement = iot_telemetry  (NOT temperature_1)"
echo "  field       = value"
echo "  filter tag  metric = temperature_1"