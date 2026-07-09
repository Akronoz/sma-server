#!/usr/bin/env bash
# Recover .env from the running container WITHOUT deleting existing lines.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=".env"
TMP="$(mktemp)"

if ! docker ps --format '{{.Names}}' | grep -qx backend; then
  echo "backend is not running. Create .env manually from .env.example"
  exit 1
fi

docker inspect backend --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E '^(SMA_API_KEY|INFLUX_TOKEN|INFLUX_ORG|INFLUX_BUCKET|INFLUX_URL|WG_CONTAINER)=' \
  > "$TMP"

if [[ -f "$OUT" ]]; then
  cp "$OUT" "${OUT}.bak.$(date +%s)"
  echo "Backup: ${OUT}.bak.*"
fi

# Keep WG_CONTAINER if it was already set
if [[ -f "$OUT" ]] && grep -q '^WG_CONTAINER=' "$OUT"; then
  grep '^WG_CONTAINER=' "$OUT" >> "$TMP"
fi

grep -q '^WG_CONTAINER=' "$TMP" || echo "WG_CONTAINER=wg-easy" >> "$TMP"
grep -q '^INFLUX_URL=' "$TMP" || echo "INFLUX_URL=http://172.17.0.1:8086" >> "$TMP"

sort -u -t= -k1,1 "$TMP" > "$OUT"
rm -f "$TMP"

echo "Wrote $OUT ($(wc -l < "$OUT") lines). Review:"
grep -E '^(SMA_API_KEY|INFLUX_|WG_)' "$OUT" | while IFS= read -r line; do
  k="${line%%=*}"
  v="${line#*=}"
  if [[ "$k" == *TOKEN* || "$k" == *KEY* ]]; then
    echo "  $k=${v:0:4}…"
  else
    echo "  $line"
  fi
done