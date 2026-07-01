#!/usr/bin/env python3
"""
API en el VPS: recibe snapshots de la RPi y los escribe en InfluxDB.

Variables de entorno:
  SMA_API_KEY        Clave compartida con sma_push.py (obligatoria)
  INFLUX_URL         URL de InfluxDB (ej. http://localhost:8086)
  INFLUX_TOKEN       Token con permiso de escritura
  INFLUX_ORG         Organización InfluxDB
  INFLUX_BUCKET      Bucket destino (ej. sma)

Uso:
  uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sma-server")

from fastapi import FastAPI, Header, HTTPException
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

API_KEY = os.environ.get("SMA_API_KEY", "").strip()
INFLUX_URL = os.environ.get("INFLUX_URL", "http://localhost:8086").strip()
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "").strip()
INFLUX_ORG = os.environ.get("INFLUX_ORG", "").strip()
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "sma").strip()

app = FastAPI(title="SMA Ingest API", version="1.0")

_influx: InfluxDBClient | None = None
_write_api = None
_query_api = None


def _metric(payload: dict, *keys: str) -> float | None:
    node: Any = payload
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return float(node) if isinstance(node, (int, float)) else None


def _plant_timestamp(payload: dict) -> str | None:
    for key in ("timestamp", "sent_at"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _get_client() -> InfluxDBClient:
    global _influx
    if not INFLUX_TOKEN or not INFLUX_ORG:
        raise HTTPException(status_code=500, detail="InfluxDB no configurado")
    if _influx is None:
        _influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    return _influx


def _get_write_api():
    global _write_api
    if _write_api is None:
        _write_api = _get_client().write_api(write_options=SYNCHRONOUS)
    return _write_api


def _get_query_api():
    global _query_api
    if _query_api is None:
        _query_api = _get_client().query_api()
    return _query_api


def _verify_api_key(header_key: str | None) -> None:
    if not API_KEY:
        raise HTTPException(status_code=500, detail="SMA_API_KEY no configurada")
    if header_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida")


def _payload_to_point(payload: dict) -> Point:
    host = str(payload.get("host", "unknown"))
    # Hora de ingesta en UTC real. El timestamp de la planta va como campo
    # (la RPi envía hora local sin zona; si se usa como UTC queda en el futuro
    # y Flux con stop=now() no lo devuelve).
    point = (
        Point("sma_plant")
        .tag("host", host)
        .tag("inverter_unit", str(payload.get("inverter_unit", "")))
        .tag("meter_unit", str(payload.get("meter_unit", "")))
        .time(datetime.now(timezone.utc))
    )
    plant_ts = _plant_timestamp(payload)
    if plant_ts:
        point = point.field("plant_timestamp", plant_ts)

    fields: dict[str, float] = {
        "inverter_power_w": _metric(payload, "inverter_power", "value"),
        "meter_import_kw": _metric(payload, "meter_import", "value"),
        "meter_export_kw": _metric(payload, "meter_export", "value"),
        "meter_balance_kw": _metric(payload, "meter_balance", "value"),
        "site_consumption_kw": _metric(payload, "site_consumption", "value"),
        "meter_apparent_kva": _metric(payload, "meter_apparent_total", "value"),
        "meter_frequency_hz": _metric(payload, "meter_frequency", "value"),
        "read_duration_s": payload.get("read_duration_s"),
    }

    for name, value in fields.items():
        if value is not None:
            point = point.field(name, float(value))

    has_metric = any(value is not None for value in fields.values())
    if not has_metric:
        raise HTTPException(status_code=422, detail="Payload sin métricas válidas")

    return point


@app.on_event("shutdown")
def shutdown() -> None:
    global _influx, _write_api, _query_api
    if _influx:
        _influx.close()
    _influx = None
    _write_api = None
    _query_api = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {
        "api_key_set": bool(API_KEY),
        "influx_url": INFLUX_URL,
        "influx_org_set": bool(INFLUX_ORG),
        "influx_token_set": bool(INFLUX_TOKEN),
        "influx_bucket": INFLUX_BUCKET,
    }


@app.post("/api/v1/snapshots")
def ingest_snapshot(
    payload: dict,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _verify_api_key(x_api_key)

    point = _payload_to_point(payload)
    metrics = [
        _metric(payload, "inverter_power", "value"),
        _metric(payload, "meter_import", "value"),
        _metric(payload, "meter_export", "value"),
        _metric(payload, "meter_balance", "value"),
        _metric(payload, "site_consumption", "value"),
        _metric(payload, "meter_apparent_total", "value"),
        _metric(payload, "meter_frequency", "value"),
    ]
    field_count = sum(1 for m in metrics if m is not None) + (
        1 if payload.get("read_duration_s") is not None else 0
    )
    logger.info("Escribiendo punto en %s/%s (%d campos)", INFLUX_ORG, INFLUX_BUCKET, field_count)

    write_api = _get_write_api()
    try:
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
    except Exception as exc:  # noqa: BLE001
        logger.error("Influx write falló: %s", exc)
        raise HTTPException(status_code=502, detail=f"Error escribiendo en InfluxDB: {exc}") from exc

    logger.info("Influx write OK")
    return {
        "ok": True,
        "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fields_written": field_count,
    }


def _collect_latest_records(tables) -> dict[str, Any]:
    by_time: dict[datetime, dict[str, Any]] = {}
    for table in tables:
        for record in table.records:
            record_time = record.get_time()
            if record_time is None:
                continue
            entry = by_time.setdefault(record_time, {})
            field = record.get_field()
            if field:
                entry[field] = record.get_value()
            for tag in ("host", "inverter_unit", "meter_unit"):
                value = record.values.get(tag)
                if value is not None:
                    entry[tag] = value

    if not by_time:
        return {}

    latest_time = max(by_time)
    data = by_time[latest_time]
    data["time"] = latest_time.isoformat()
    return data


@app.get("/api/v1/snapshots/latest")
def latest_snapshot() -> dict:
    query = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -30d, stop: now() + 1d)
  |> filter(fn: (r) => r._measurement == "sma_plant")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 50)
'''
    try:
        tables = _get_query_api().query(query=query, org=INFLUX_ORG)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Error leyendo InfluxDB: {exc}") from exc

    data = _collect_latest_records(tables)
    if not data:
        raise HTTPException(status_code=404, detail="Sin datos todavía")
    return data