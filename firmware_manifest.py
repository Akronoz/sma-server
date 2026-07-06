"""Latest ESP firmware version reported by the IoT gateway (RPi OTA staging)."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).with_name("data") / "firmware_manifest.json"


class FirmwareManifestStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_PATH
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict):
            self._data = raw

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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