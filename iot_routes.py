"""Rutas FastAPI para telemetría IoT, comandos y config de máquinas."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException
from influxdb_client import Point

from devices_store import DevicesStore
from iot_commands import CommandStore
from machines_config import MachinesConfigStore

logger = logging.getLogger("sma-server.iot")

router = APIRouter(prefix="/api/v1/iot", tags=["iot"])

_commands_path = os.environ.get("IOT_COMMANDS_PATH", "").strip()
_config_path = os.environ.get("MACHINES_CONFIG_PATH", "").strip()
_devices_path = os.environ.get("IOT_DEVICES_PATH", "").strip()

_command_store = CommandStore(Path(_commands_path) if _commands_path else None)
_machines_store = MachinesConfigStore(Path(_config_path) if _config_path else None)
_devices_store = DevicesStore(Path(_devices_path) if _devices_path else None)

_get_write_api: Callable[[], Any] | None = None
_influx_org = ""
_influx_bucket = ""
_verify_api_key: Callable[[str | None], None] | None = None


def configure_iot_routes(
    *,
    get_write_api: Callable[[], Any],
    influx_org: str,
    influx_bucket: str,
    verify_api_key: Callable[[str | None], None],
) -> None:
    global _get_write_api, _influx_org, _influx_bucket, _verify_api_key
    _get_write_api = get_write_api
    _influx_org = influx_org
    _influx_bucket = influx_bucket
    _verify_api_key = verify_api_key


def _require_auth(x_api_key: str | None) -> None:
    if _verify_api_key is None:
        raise HTTPException(status_code=500, detail="Rutas IoT no configuradas")
    _verify_api_key(x_api_key)


def _parse_event_time(event: dict) -> datetime:
    received_at = event.get("received_at")
    if isinstance(received_at, str) and received_at.strip():
        text = received_at.strip().replace(" ", "T")
        try:
            if text.endswith("Z"):
                return datetime.fromisoformat(text.replace("Z", "+00:00"))
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _coerce_numeric(value: Any, payload: Any) -> float | int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return float(value)
    if payload is None:
        return None
    text = str(payload).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return None


def _telemetry_to_point(event: dict) -> Point | None:
    device_id = str(event.get("device_id", "")).strip()
    if not device_id:
        return None

    metric = str(event.get("metric", event.get("category", "unknown")))
    channel = event.get("channel")
    payload = event.get("payload")
    numeric = _coerce_numeric(event.get("value"), payload)

    point = (
        Point("iot_telemetry")
        .tag("device_id", device_id)
        .tag("metric", metric)
        .time(_parse_event_time(event))
    )
    if channel is not None:
        point = point.tag("channel", str(channel))

    if numeric is None:
        if payload is None:
            return None
        point = point.field("value_str", str(payload))
    else:
        point = point.field("value", float(numeric))

    payload_text = event.get("payload")
    if payload_text is not None:
        point = point.field("payload", str(payload_text))

    received_at = event.get("received_at")
    if isinstance(received_at, str) and received_at.strip():
        point = point.field("device_timestamp", received_at.strip())

    return point


@router.post("/telemetry")
def ingest_telemetry(
    payload: dict,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)

    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise HTTPException(status_code=422, detail="Se requiere events[]")

    points = []
    for event in events:
        if not isinstance(event, dict):
            continue
        point = _telemetry_to_point(event)
        if point is not None:
            points.append(point)

    if not points:
        raise HTTPException(status_code=422, detail="Sin eventos válidos")

    write_api = _get_write_api()
    try:
        write_api.write(bucket=_influx_bucket, org=_influx_org, record=points)
    except Exception as exc:  # noqa: BLE001
        logger.error("Influx write IoT falló: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error escribiendo en InfluxDB: {exc}") from exc

    summaries: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        dev = str(event.get("device_id", ""))
        met = str(event.get("metric", ""))
        if not dev or not met:
            continue
        num = _coerce_numeric(event.get("value"), event.get("payload"))
        if num is not None and met.startswith("temperature"):
            summaries.append(f"{dev}/{met}={num:g}")
        elif num is not None:
            summaries.append(f"{dev}/{met}={num:g}")
    logger.info(
        "IoT telemetría → Influx: %d puntos, bucket=%s%s",
        len(points),
        _influx_bucket,
        f" ({', '.join(summaries)})" if summaries else "",
    )

    return {"ok": True, "written": len(points)}


@router.get("/commands/pending")
def pending_commands(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)
    commands = [cmd.to_public() for cmd in _command_store.list_pending()]
    return {"commands": commands}


@router.post("/commands")
def create_command(
    payload: dict,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)

    device_id = str(payload.get("device_id", "")).strip()
    action = str(payload.get("action", "")).strip()
    if not device_id or not action:
        raise HTTPException(status_code=422, detail="device_id y action son obligatorios")

    output = payload.get("output")
    state = payload.get("state")
    output_int = int(output) if output is not None else None
    state_bool = bool(state) if state is not None else None

    if action == "set_output" and (output_int is None or state_bool is None):
        raise HTTPException(status_code=422, detail="set_output requiere output y state")

    command = _command_store.enqueue(
        device_id=device_id,
        action=action,
        output=output_int,
        state=state_bool,
    )
    return {"ok": True, "command": command.to_public()}


@router.post("/commands/{command_id}/ack")
def ack_command(
    command_id: str,
    payload: dict,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)
    ok = bool(payload.get("ok"))
    detail = str(payload.get("detail", ""))
    command = _command_store.acknowledge(command_id, ok=ok, detail=detail)
    if command is None:
        raise HTTPException(status_code=404, detail="Comando no encontrado")
    return {"ok": True, "command": command.to_public()}


@router.get("/machines/config")
def get_machines_config(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)
    return _machines_store.get()


@router.get("/devices")
def list_devices(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)
    return {"devices": _devices_store.list_devices()}


@router.post("/devices")
def register_device(
    payload: dict,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)
    device_id = str(payload.get("device_id", "")).strip()
    if not device_id:
        raise HTTPException(status_code=422, detail="device_id requerido")
    try:
        device = _devices_store.register(device_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "device": device}


@router.put("/devices/{device_id}/name")
def rename_device(
    device_id: str,
    payload: dict,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)
    name = payload.get("name")
    name_str = str(name).strip() if name is not None else None
    device = _devices_store.update_name(device_id, name_str)
    return {"ok": True, "device": device}


@router.put("/machines/config")
def put_machines_config(
    payload: dict,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_auth(x_api_key)
    try:
        data = _machines_store.replace(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "config": data}