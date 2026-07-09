#!/bin/bash
# Monitor SMA data arrival on the console.
# Usage: ./scripts/monitor.sh
#        ./scripts/monitor.sh http://10.8.0.1:8000 10

API="${1:-http://10.8.0.1:8000}"
INTERVAL="${2:-10}"

echo "Monitoring SMA -> $API/api/v1/snapshots/latest every ${INTERVAL}s (Ctrl+C to exit)"
echo ""

LAST_TIME=""
while true; do
  NOW=$(date '+%Y-%m-%d %H:%M:%S')
  RESP=$(curl -sf "$API/api/v1/snapshots/latest" 2>/dev/null) || {
    echo "[$NOW] NO RESPONSE — is the backend up?"
    sleep "$INTERVAL"
    continue
  }

  TIME=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('time',''))" 2>/dev/null)
  PROD=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('inverter_power_kw'); print(v if v is not None else (float(d.get('inverter_power_w',0))/1000 if d.get('inverter_power_w') is not None else '?'))" 2>/dev/null)
  CONS=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('site_consumption_kw','?'))" 2>/dev/null)
  HOST=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('host','?'))" 2>/dev/null)
  PLANT=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('plant_timestamp',''))" 2>/dev/null)

  if [ "$TIME" != "$LAST_TIME" ]; then
    echo "[$NOW] NEW DATA | host=$HOST | prod=${PROD}kW | consumption=${CONS}kW | plant=$PLANT | ingested=$TIME"
    LAST_TIME="$TIME"
  else
    echo "[$NOW] no change (last: $TIME)"
  fi

  sleep "$INTERVAL"
done