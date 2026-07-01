#!/bin/bash
# Monitoriza llegada de datos SMA en consola.
# Uso: ./scripts/monitor.sh
#      ./scripts/monitor.sh http://10.8.0.1:8000 10

API="${1:-http://10.8.0.1:8000}"
INTERVAL="${2:-10}"

echo "Monitor SMA → $API/api/v1/snapshots/latest cada ${INTERVAL}s (Ctrl+C salir)"
echo ""

LAST_TIME=""
while true; do
  NOW=$(date '+%Y-%m-%d %H:%M:%S')
  RESP=$(curl -sf "$API/api/v1/snapshots/latest" 2>/dev/null) || {
    echo "[$NOW] SIN RESPUESTA — ¿sma-server arriba?"
    sleep "$INTERVAL"
    continue
  }

  TIME=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('time',''))" 2>/dev/null)
  PROD=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('inverter_power_w','?'))" 2>/dev/null)
  CONS=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('site_consumption_kw','?'))" 2>/dev/null)
  HOST=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('host','?'))" 2>/dev/null)
  PLANT=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('plant_timestamp',''))" 2>/dev/null)

  if [ "$TIME" != "$LAST_TIME" ]; then
    echo "[$NOW] NUEVO DATO | host=$HOST | prod=${PROD}W | consumo=${CONS}kW | planta=$PLANT | ingesta=$TIME"
    LAST_TIME="$TIME"
  else
    echo "[$NOW] sin cambios (último: $TIME)"
  fi

  sleep "$INTERVAL"
done