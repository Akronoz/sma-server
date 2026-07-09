#!/usr/bin/env bash
# Deploy backend on the wg-easy network (Gironasa production).
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

WG_CONTAINER="${WG_CONTAINER:-wg-easy}"

echo "=== WireGuard containers ==="
docker ps --format '{{.Names}}' | grep -i wg || true
echo ""

if ! docker ps --format '{{.Names}}' | grep -qx "$WG_CONTAINER"; then
  echo "ERROR: '$WG_CONTAINER' is not running."
  echo "Set WG_CONTAINER in .env (exact name from docker ps)."
  exit 1
fi

echo "=== Recreate backend on network of: $WG_CONTAINER ==="
docker rm -f backend 2>/dev/null || true
docker compose up -d --build

echo "Waiting for uvicorn startup..."
sleep 4

echo ""
echo "=== Status ==="
docker ps -a --filter name=backend --format 'table {{.Names}}\t{{.Status}}'
echo "NetworkMode=$(docker inspect backend --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || echo '?')"

echo ""
echo "=== Backend logs (last 15 lines) ==="
docker logs backend --tail 15 2>&1 || true

_probe() {
  local label="$1"
  local cmd="$2"
  echo -n "  $label -> "
  if eval "$cmd" >/dev/null 2>&1; then
    eval "$cmd" 2>/dev/null | head -c 200
    echo ""
    echo "  OK"
    return 0
  fi
  echo "FAILED"
  return 1
}

echo ""
echo "=== Health checks ==="
OK_ANY=0
_probe "localhost:8000 (inside backend)" \
  "docker exec backend python -c \"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read().decode())\"" \
  && OK_ANY=1 || true

_probe "localhost:8000 (inside $WG_CONTAINER)" \
  "docker exec $WG_CONTAINER wget -qO- http://127.0.0.1:8000/health 2>/dev/null" \
  && OK_ANY=1 || true

_probe "10.8.0.1:8000 (from VPS host)" \
  "curl -sf --connect-timeout 3 http://10.8.0.1:8000/health" \
  && OK_ANY=1 || true

echo ""
if [[ "$OK_ANY" -eq 1 ]]; then
  echo "backend responds. Test from the RPi:"
  echo "  curl -s http://10.8.0.1:8000/health"
else
  echo "ERROR: backend not responding on any check."
  echo "Check: docker logs backend --tail 50"
  echo "Does .env have SMA_API_KEY, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET?"
  exit 1
fi