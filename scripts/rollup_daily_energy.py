#!/usr/bin/env python3
"""
Compute daily kWh from sma_plant and write sma_energy_day to Influx.

Usage:
  python scripts/rollup_daily_energy.py --yesterday
  python scripts/rollup_daily_energy.py --date 2026-07-01
  python scripts/rollup_daily_energy.py --backfill
  python scripts/rollup_daily_energy.py --from 2026-06-01 --to 2026-06-30

Recommended cron (00:05 server time; adjust TZ if needed):
  5 0 * * * cd ~/gironasa/backend && set -a && . ./.env && set +a && venv/bin/python3 scripts/rollup_daily_energy.py --yesterday
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from influxdb_client import InfluxDBClient

from energy_daily import (
    iter_ymd_range,
    query_earliest_raw_ymd,
    rollup_day,
    today_ymd_in_plant,
    ymd_in_plant_tz,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("rollup_daily_energy")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _client() -> InfluxDBClient:
    url = _env("INFLUX_URL", "http://localhost:8086")
    token = _env("INFLUX_TOKEN")
    org = _env("INFLUX_ORG")
    if not token or not org:
        raise SystemExit("Missing INFLUX_TOKEN or INFLUX_ORG")
    return InfluxDBClient(url=url, token=token, org=org)


def _yesterday_ymd() -> str:
    today = today_ymd_in_plant()
    y, m, d = (int(x) for x in today.split("-"))
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(os.environ.get("PLANT_TIMEZONE", "Europe/Madrid"))
    local = datetime(y, m, d, tzinfo=tz) - timedelta(days=1)
    return ymd_in_plant_tz(local.astimezone(timezone.utc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily rollup sma_plant -> sma_energy_day")
    parser.add_argument("--date", help="Day YYYY-MM-DD")
    parser.add_argument("--yesterday", action="store_true", help="Yesterday (closed day)")
    parser.add_argument("--backfill", action="store_true", help="From first data point through yesterday")
    parser.add_argument("--from", dest="from_date", help="Start YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="End YYYY-MM-DD")
    parser.add_argument("--host", default=_env("SMA_HOST", "gironasa"))
    args = parser.parse_args()

    bucket = _env("INFLUX_BUCKET", "sma")
    client = _client()

    try:
        if args.yesterday:
            dates = [_yesterday_ymd()]
        elif args.date:
            dates = [args.date]
        elif args.backfill:
            earliest = query_earliest_raw_ymd(client, _env("INFLUX_ORG"), bucket)
            if not earliest:
                raise SystemExit("No data in sma_plant")
            dates = list(iter_ymd_range(earliest, _yesterday_ymd()))
        elif args.from_date and args.to_date:
            dates = list(iter_ymd_range(args.from_date, args.to_date))
        else:
            parser.error("Specify --yesterday, --date, --backfill, or --from/--to")

        written = 0
        skipped = 0
        for ymd in dates:
            result = rollup_day(
                client,
                _env("INFLUX_ORG"),
                bucket,
                ymd,
                host=args.host,
            )
            if result is None:
                skipped += 1
                logger.info("%s: no data", ymd)
            else:
                written += 1
                logger.info(
                    "%s: prod=%.1f cons=%.1f export_net=%.1f peak=%.1f kW",
                    ymd,
                    result.production_kwh,
                    result.consumption_kwh,
                    result.export_net_kwh,
                    result.peak_production_kw,
                )

        logger.info("Done: %d written, %d skipped", written, skipped)
    finally:
        client.close()


if __name__ == "__main__":
    main()