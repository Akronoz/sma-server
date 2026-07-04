#!/usr/bin/env bash
# Despliega sma-server en red wg-easy (producción Gironasa).
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

WG_CONTAINER="${WG_CONTAINER:-wg-easy}"

echo "=== Contenedores WireGuard ==="
docker ps --format '{{.Names}}' | grep -i wg || true
echo ""

if ! docker ps --format '{{.Names}}' | grep -qx "$WG_CONTAINER"; then
  echo "ERROR: no está corriendo '$WG_CONTAINER'."
  echo "Ajusta WG_CONTAINER en .env (nombre exacto de docker ps)."
  exit 1
fi

echo "=== Recrear sma-server en red de: $WG_CONTAINER ==="
docker rm -f sma-server 2>/dev/null || true
docker compose up -d --build

echo ""
echo "=== Estado ==="
docker ps --filter name=sma-server --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo "(sin puertos publicados = normal; escucha en 10.8.0.1:8000 vía VPN)"

echo ""
echo "=== Health por VPN ==="
curl -sf http://10.8.0.1:8000/health && echo "" || echo "FALLO: curl http://10.8.0.1:8000/health"
curl -sf http://10.8.0.1:8000/ready && echo "" || echo "FALLO: curl http://10.8.0.1:8000/ready"