#!/usr/bin/env bash
# Show where the running backend config comes from (without revealing full secrets).
set -euo pipefail

echo "=== .env file on disk ==="
for dir in "$HOME/gironasa/backend" "$HOME/backend" "/opt/backend" "$(pwd)"; do
  if [[ -f "$dir/.env" ]]; then
    echo "FOUND: $dir/.env"
    wc -l "$dir/.env"
  fi
done
if ! find "$HOME" -maxdepth 4 -name '.env' -path '*/backend/*' 2>/dev/null | head -5 | grep -q .; then
  echo "(no .env under ~/.../backend in usual paths)"
fi

echo ""
echo "=== Backend container ==="
if ! docker ps --format '{{.Names}}' | grep -qx backend; then
  echo "backend is NOT running"
  exit 1
fi

echo "Image / status:"
docker ps --filter name=backend --format '  {{.Names}}  {{.Image}}  {{.Status}}'

echo ""
echo "Network (wg-easy?):"
docker inspect backend --format '  NetworkMode={{.HostConfig.NetworkMode}}'

echo ""
echo "Environment variables (sensitive values truncated):"
docker inspect backend --format '{{range .Config.Env}}{{println .}}{{end}}' \
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
  echo "  http://127.0.0.1:8000/ready  OK (localhost only)"
else
  echo "  /ready not responding on 10.8.0.1 or 127.0.0.1"
fi

echo ""
echo "If PV works but there is no .env: the container kept env from a previous 'docker compose up'."
echo "If you recreate the container without .env, it will stop writing to Influx."