#!/usr/bin/env bash
# Helpers compartidos para scripts IoT (backend en wg-easy → 10.8.0.1:8000).

_iot_load_env() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)"
  if [[ -f "$root/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$root/.env"
    set +a
  fi
}

resolve_sma_base_url() {
  if [[ -n "${SMA_BASE_URL:-}" ]]; then
    echo "$SMA_BASE_URL"
    return 0
  fi
  if curl -sf --connect-timeout 2 http://10.8.0.1:8000/health >/dev/null 2>&1; then
    echo "http://10.8.0.1:8000"
    return 0
  fi
  if curl -sf --connect-timeout 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "http://127.0.0.1:8000"
    return 0
  fi
  return 1
}

purge_device_influx_direct() {
  local device_id="$1"
  python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/purge_iot_device.py" --influx-only "$device_id"
}

purge_device_registry_direct() {
  local device_id="$1"
  python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/purge_iot_device.py" --registry-only "$device_id"
}