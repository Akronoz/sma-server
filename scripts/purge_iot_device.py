#!/usr/bin/env python3
"""Purge IoT device from Influx, registry, and machines config."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_dotenv(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def resolve_api_base(env: dict[str, str]) -> str | None:
    explicit = env.get("SMA_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    for base in ("http://10.8.0.1:8000", "http://127.0.0.1:8000"):
        try:
            urllib.request.urlopen(f"{base}/health", timeout=3)
            return base
        except OSError:
            continue
    return None


def machine_device_id(entry: dict[str, Any]) -> str:
    return str(entry.get("device_id") or entry.get("deviceId") or entry.get("id") or "").strip()


def purge_influx(device_id: str, env: dict[str, str]) -> bool:
    url = env.get("INFLUX_URL", "http://127.0.0.1:8086").rstrip("/")
    org = env.get("INFLUX_ORG", "Gironasa")
    bucket = env.get("INFLUX_BUCKET", "sma")
    token = env.get("INFLUX_TOKEN", "").strip()
    if not token:
        print("ERROR: INFLUX_TOKEN not set in .env", file=sys.stderr)
        return False

    stop = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Delete all bucket data for this device_id (any measurement).
    predicate = f'device_id="{device_id}"'
    body = json.dumps(
        {
            "start": "1970-01-01T00:00:00Z",
            "stop": stop,
            "predicate": predicate,
        }
    ).encode("utf-8")

    query = urllib.parse.urlencode({"org": org, "bucket": bucket})
    req = urllib.request.Request(
        f"{url}/api/v2/delete?{query}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print(f"  Influx OK ({device_id}) HTTP {resp.status} predicate={predicate}")
            return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"  Influx FAIL ({device_id}) HTTP {exc.code}: {detail}", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"  Influx FAIL ({device_id}): {exc}", file=sys.stderr)
        return False


def count_influx_points(device_id: str, env: dict[str, str], hours: int = 720) -> int | None:
    url = env.get("INFLUX_URL", "http://127.0.0.1:8086").rstrip("/")
    org = env.get("INFLUX_ORG", "Gironasa")
    bucket = env.get("INFLUX_BUCKET", "sma")
    token = env.get("INFLUX_TOKEN", "").strip()
    if not token:
        return None

    flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r.device_id == "{device_id}")
  |> count()
  |> group()
  |> sum()
"""
    body = flux.encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/v2/query?org={urllib.parse.quote(org)}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/vnd.flux",
            "Accept": "application/csv",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, OSError):
        return None

    total = 0
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) >= 4 and parts[-1].strip().isdigit():
            total += int(parts[-1].strip())
    return total


def purge_registry(device_id: str, root: Path) -> bool:
    path = root / "data" / "iot_devices.json"
    if not path.is_file():
        print(f"  Registry: {path} does not exist")
        return False

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  Registry FAIL: invalid JSON ({exc})", file=sys.stderr)
        return False

    devices = raw.get("devices")
    if not isinstance(devices, dict) or device_id not in devices:
        print(f"  Registry: {device_id} was not in the file")
        return False

    del devices[device_id]
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  Registry OK: removed {device_id}")
    return True


def purge_machines_config(device_id: str, root: Path) -> bool:
    path = root / "data" / "machines_config.json"
    if not path.is_file():
        print(f"  Machines config: {path} does not exist")
        return False

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  Machines config FAIL: invalid JSON ({exc})", file=sys.stderr)
        return False

    machines = raw.get("machines")
    if not isinstance(machines, list):
        print("  Machines config: no machines list")
        return False

    before = len(machines)
    machines[:] = [m for m in machines if machine_device_id(m) != device_id]
    removed = before - len(machines)

    ambient = raw.get("ambientTemperatureSource")
    if isinstance(ambient, dict):
        amb_id = str(ambient.get("deviceId") or ambient.get("device_id") or "").strip()
        if amb_id == device_id:
            raw.pop("ambientTemperatureSource", None)
            print(f"  Machines config: ambientTemperatureSource pointed to {device_id} (removed)")

    if removed == 0:
        print(f"  Machines config: {device_id} was not in the list")
        return False

    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  Machines config OK: removed {removed} entry/entries for {device_id}")
    return True


def purge_api(device_id: str, env: dict[str, str]) -> bool:
    api_key = env.get("SMA_API_KEY", "").strip()
    base = resolve_api_base(env)
    if not api_key or not base:
        print("  API: skipped (no SMA_API_KEY or /health unavailable)")
        return False

    query = urllib.parse.urlencode({"purge_influx": "true"})
    req = urllib.request.Request(
        f"{base}/api/v1/iot/devices/{urllib.parse.quote(device_id)}?{query}",
        method="DELETE",
        headers={"X-API-Key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"  API OK ({device_id}) HTTP {resp.status}: {body}")
            return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"  API FAIL ({device_id}) HTTP {exc.code}: {detail}", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"  API FAIL ({device_id}): {exc}", file=sys.stderr)
        return False


def purge_all(device_id: str, root: Path, env: dict[str, str]) -> bool:
    ok = True
    api_ok = purge_api(device_id, env)
    if not api_ok:
        ok = purge_influx(device_id, env) and ok
        ok = purge_registry(device_id, root) and ok
    else:
        purge_registry(device_id, root)
    ok = purge_machines_config(device_id, root) and ok

    remaining = count_influx_points(device_id, env)
    if remaining is None:
        print(f"  Influx verify: could not count points for {device_id}")
    elif remaining == 0:
        print(f"  Influx verify: 0 points (30d) for {device_id}")
    else:
        print(
            f"  Influx verify: STILL {remaining} point(s) (30d) for {device_id}",
            file=sys.stderr,
        )
        ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge IoT device(s)")
    parser.add_argument("device_ids", nargs="+", help="device_id to remove")
    parser.add_argument("--influx-only", action="store_true")
    parser.add_argument("--registry-only", action="store_true")
    parser.add_argument("--config-only", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    env = load_dotenv(root / ".env")

    ok = True
    for device_id in args.device_ids:
        device_id = device_id.strip()
        if not device_id:
            continue
        print(f"==> {device_id}")

        if args.registry_only:
            ok = purge_registry(device_id, root) and ok
            continue
        if args.config_only:
            ok = purge_machines_config(device_id, root) and ok
            continue
        if args.influx_only:
            ok = purge_influx(device_id, env) and ok
            continue

        ok = purge_all(device_id, root, env) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())