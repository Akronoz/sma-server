#!/usr/bin/env bash
# Muestra de dónde sale la config del sma-server en marcha (sin revelar secretos completos).
set -euo pipefail

echo "=== Archivo .env en disco ==="
for dir in "$HOME/gironasa/sma-server" "$HOME/sma-server" "/opt/sma-server" "$(pwd)"; do
  if [[ -f "$dir/.env" ]]; then
    echo "ENCONTRADO: $dir/.env"
    wc -l "$dir/.env"
  fi
done
if ! find "$HOME" -maxdepth 4 -name '.env' -path '*/sma-server/*' 2>/dev/null | head -5 | grep -q .; then
  echo "(no hay .env bajo ~/.../sma-server en las rutas habituales)"
fi

echo ""
echo "=== Contenedor sma-server ==="
if ! docker ps --format '{{.Names}}' | grep -qx sma-server; then
  echo "sma-server NO está corriendo"
  exit 1
fi

echo "Imagen / estado:"
docker ps --filter name=sma-server --format '  {{.Names}}  {{.Image}}  {{.Status}}'

echo ""
echo "Red (¿wg-easy?):"
docker inspect sma-server --format '  NetworkMode={{.HostConfig.NetworkMode}}'

echo ""
echo "Variables de entorno (valores sensibles truncados):"
docker inspect sma-server --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E '^(SMA_|INFLUX_|WG_|IOT_)' \
  | while IFS= read -r line; do
      key="${line%%=*}"
      val="${line#*=}"
      if [[ "$key" == *TOKEN* || "$key" == *KEY* ]]; then
        echo "  $key=${val:0:4}…${val: -4} (len=${#val})"
      else
        echo "  $line"
      fi
    done

echo ""
echo "=== Health API ==="
if curl -sf http://10.8.0.1:8000/ready >/dev/null 2>&1; then
  echo "  http://10.8.0.1:8000/ready  OK (VPN/wg-easy)"
elif curl -sf http://127.0.0.1:8000/ready >/dev/null 2>&1; then
  echo "  http://127.0.0.1:8000/ready  OK (solo localhost)"
else
  echo "  /ready no responde en 10.8.0.1 ni 127.0.0.1"
fi

echo ""
echo "Si FV funciona pero no hay .env: el contenedor conserva env de un 'docker compose up' anterior."
echo "Si recreas el contenedor sin .env, dejará de escribir en Influx."