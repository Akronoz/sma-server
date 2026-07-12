"""IoT device registry (ESP serial) and names assigned from the web."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from json_io import atomic_write_json, read_json

DEFAULT_DEVICES = Path(__file__).with_name("data") / "iot_devices.json"


class DevicesStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_DEVICES
        self._lock = threading.Lock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        raw = read_json(self.path, default=None)
        if isinstance(raw, dict) and isinstance(raw.get("devices"), dict):
            self._devices = raw["devices"]

    def _save(self) -> None:
        atomic_write_json(self.path, {"devices": self._devices})

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(v) for v in self._devices.values()]

    def register(self, device_id: str) -> dict[str, Any]:
        device_id = device_id.strip()
        if not device_id:
            raise ValueError("device_id vacío")
        with self._lock:
            if device_id not in self._devices:
                self._devices[device_id] = {
                    "device_id": device_id,
                    "name": None,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }
            else:
                self._devices[device_id]["last_seen"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return deepcopy(self._devices[device_id])

    def remove(self, device_id: str) -> bool:
        device_id = device_id.strip()
        if not device_id:
            raise ValueError("device_id vacío")
        with self._lock:
            if device_id not in self._devices:
                return False
            del self._devices[device_id]
            self._save()
            return True

    def update_name(self, device_id: str, name: str | None) -> dict[str, Any]:
        device_id = device_id.strip()
        with self._lock:
            entry = self._devices.setdefault(
                device_id,
                {
                    "device_id": device_id,
                    "name": None,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                },
            )
            entry["name"] = name.strip() if name else None
            entry["last_seen"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return deepcopy(entry)
