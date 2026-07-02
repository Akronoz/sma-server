"""
Integración diaria de energía desde sma_plant → sma_energy_day.

Un punto por día calendario (TZ planta) con kWh acumulados y pico kW.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

MEASUREMENT_RAW = "sma_plant"
MEASUREMENT_DAILY = "sma_energy_day"

FIELD_PRODUCTION_W = "inverter_power_w"
FIELD_CONSUMPTION_KW = "site_consumption_kw"
FIELD_EXPORT_KW = "meter_balance_kw"

FIELD_PRODUCTION_KWH = "production_kwh"
FIELD_CONSUMPTION_KWH = "consumption_kwh"
FIELD_EXPORT_NET_KWH = "export_net_kwh"
FIELD_PEAK_PRODUCTION_KW = "peak_production_kw"


@dataclass(frozen=True)
class DailyEnergy:
    ymd: str
    production_kwh: float
    consumption_kwh: float
    export_net_kwh: float
    peak_production_kw: float


def plant_tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("PLANT_TIMEZONE", "Europe/Madrid"))


def ymd_in_plant_tz(dt: datetime) -> str:
    tz = plant_tz()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d")


def start_of_day_utc(ymd: str) -> datetime:
    y, m, d = (int(x) for x in ymd.split("-"))
    local = datetime(y, m, d, 0, 0, 0, tzinfo=plant_tz())
    return local.astimezone(timezone.utc)


def end_of_day_utc(ymd: str) -> datetime:
    return start_of_day_utc(ymd) + timedelta(days=1)


def today_ymd_in_plant() -> str:
    return ymd_in_plant_tz(datetime.now(timezone.utc))


def integrate_kwh(points: list[tuple[datetime, float]]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        t0, v0 = points[i - 1]
        t1, v1 = points[i]
        dt_h = (t1 - t0).total_seconds() / 3600.0
        avg = (v0 + v1) / 2.0
        total += max(0.0, avg * dt_h)
    return total


def integrate_signed_kwh(points: list[tuple[datetime, float]]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        t0, v0 = points[i - 1]
        t1, v1 = points[i]
        dt_h = (t1 - t0).total_seconds() / 3600.0
        avg = (v0 + v1) / 2.0
        total += avg * dt_h
    return total


def _scale_raw(field: str, value: float) -> float:
    if field == FIELD_PRODUCTION_W:
        return value / 1000.0
    return value


def _query_field_series(
    client: InfluxDBClient,
    org: str,
    bucket: str,
    field: str,
    start: datetime,
    stop: datetime,
) -> list[tuple[datetime, float]]:
    query = f'''
from(bucket: "{bucket}")
  |> range(start: time(v: "{start.isoformat()}"), stop: time(v: "{stop.isoformat()}"))
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_RAW}" and r._field == "{field}")
  |> sort(columns: ["_time"])
'''
    tables = client.query_api().query(query=query, org=org)
    points: list[tuple[datetime, float]] = []
    for table in tables:
        for record in table.records:
            ts = record.get_time()
            value = record.get_value()
            if ts is None or value is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            points.append((ts, _scale_raw(field, float(value))))
    points.sort(key=lambda item: item[0])
    return points


def compute_daily_energy(
    client: InfluxDBClient,
    org: str,
    bucket: str,
    ymd: str,
    *,
    stop: datetime | None = None,
) -> DailyEnergy | None:
    start = start_of_day_utc(ymd)
    day_stop = stop if stop is not None else end_of_day_utc(ymd)
    if day_stop <= start:
        return None

    production = _query_field_series(
        client, org, bucket, FIELD_PRODUCTION_W, start, day_stop
    )
    consumption = _query_field_series(
        client, org, bucket, FIELD_CONSUMPTION_KW, start, day_stop
    )
    export_pts = _query_field_series(
        client, org, bucket, FIELD_EXPORT_KW, start, day_stop
    )

    if not production and not consumption and not export_pts:
        return None

    peak = max((v for _, v in production), default=0.0)
    return DailyEnergy(
        ymd=ymd,
        production_kwh=integrate_kwh(production),
        consumption_kwh=integrate_kwh(consumption),
        export_net_kwh=integrate_signed_kwh(export_pts),
        peak_production_kw=peak,
    )


def daily_energy_to_point(energy: DailyEnergy, host: str = "gironasa") -> Point:
    ts = start_of_day_utc(energy.ymd)
    return (
        Point(MEASUREMENT_DAILY)
        .tag("host", host)
        .time(ts)
        .field(FIELD_PRODUCTION_KWH, float(energy.production_kwh))
        .field(FIELD_CONSUMPTION_KWH, float(energy.consumption_kwh))
        .field(FIELD_EXPORT_NET_KWH, float(energy.export_net_kwh))
        .field(FIELD_PEAK_PRODUCTION_KW, float(energy.peak_production_kw))
    )


def write_daily_energy(
    client: InfluxDBClient,
    org: str,
    bucket: str,
    energy: DailyEnergy,
    host: str = "gironasa",
) -> None:
    write_api = client.write_api(write_options=SYNCHRONOUS)
    write_api.write(bucket=bucket, org=org, record=daily_energy_to_point(energy, host=host))


def rollup_day(
    client: InfluxDBClient,
    org: str,
    bucket: str,
    ymd: str,
    *,
    stop: datetime | None = None,
    host: str = "gironasa",
) -> DailyEnergy | None:
    energy = compute_daily_energy(client, org, bucket, ymd, stop=stop)
    if energy is None:
        return None
    write_daily_energy(client, org, bucket, energy, host=host)
    return energy


def iter_ymd_range(start_ymd: str, end_ymd: str) -> Iterable[str]:
    cursor = start_ymd
    while cursor <= end_ymd:
        yield cursor
        y, m, d = (int(x) for x in cursor.split("-"))
        local = datetime(y, m, d, tzinfo=plant_tz()) + timedelta(days=1)
        cursor = ymd_in_plant_tz(local.astimezone(timezone.utc))


def query_earliest_raw_ymd(client: InfluxDBClient, org: str, bucket: str) -> str | None:
    query = f'''
from(bucket: "{bucket}")
  |> range(start: -5y)
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_RAW}" and r._field == "{FIELD_PRODUCTION_W}")
  |> first()
  |> keep(columns: ["_time"])
'''
    tables = client.query_api().query(query=query, org=org)
    for table in tables:
        for record in table.records:
            ts = record.get_time()
            if ts is not None:
                return ymd_in_plant_tz(ts)
    return None