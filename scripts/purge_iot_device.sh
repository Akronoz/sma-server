#!/usr/bin/env bash
# Purge IoT devices (Influx + data/iot_devices.json).
# Usage:
#   bash scripts/purge_iot_device.sh homeassistant niquel
#   bash scripts/purge_iot_device.sh --influx-only homeassistant
#   bash scripts/purge_iot_device.sh --registry-only niquel
#   bash scripts/purge_iot_device.sh --config-only niquel

set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 "$(dirname "$0")/purge_iot_device.py" "$@"