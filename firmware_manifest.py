"""Latest ESP firmware version reported by the IoT gateway (RPi OTA staging)."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from json_io import atomic_write_json, read_json

DEFAULT_PATH = Path(__file__).with_name("data") / "firmware_manifest.json"


class FirmwareManifestStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_PATH
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        raw = read_json(self.path, default=None)
        if isinstance(raw, dict):
            self._data = raw

    def _save(self) -> None:
        atomic_write_json(self.path, self._data)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def replace(self, version: str) -> dict[str, Any]:
        text = version.strip()
        if not text:
            raise ValueError("version requerida")
        with self._lock:
            self._data = {
                "version": text,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save()
            return deepcopy(self._data)
