"""Machine configuration persistence (timeline, device_id, outputs)."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path(__file__).with_name("data") / "machines_config.json"

DEFAULT_MACHINES: dict[str, Any] = {"machines": []}


def _normalize_ambient_source(source: Any) -> dict[str, str] | None:
    if not isinstance(source, dict):
        return None
    device_id = str(source.get("deviceId") or source.get("device_id") or "").strip()
    channel = str(source.get("channel") or "").strip()
    if not device_id or channel not in ("1", "2", "3"):
        return None
    normalized: dict[str, str] = {"deviceId": device_id, "channel": channel}
    label = str(source.get("label") or "").strip()
    if label:
        normalized["label"] = label
    return normalized


class MachinesConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_CONFIG
        self._lock = threading.Lock()
        self._data = deepcopy(DEFAULT_MACHINES)
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            self._save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict) and isinstance(raw.get("machines"), list):
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

    def replace(self, payload: dict[str, Any]) -> dict[str, Any]:
        machines = payload.get("machines")
        if not isinstance(machines, list):
            raise ValueError("payload.machines debe ser una lista")
        with self._lock:
            previous_ambient = self._data.get("ambientTemperatureSource")
            self._data = {"machines": machines}
            if "ambientTemperatureSource" in payload:
                source = payload.get("ambientTemperatureSource")
                if source is None:
                    self._data.pop("ambientTemperatureSource", None)
                else:
                    normalized = _normalize_ambient_source(source)
                    if normalized is None:
                        raise ValueError(
                            "ambientTemperatureSource inválido (equipo y sonda T1-T3)"
                        )
                    self._data["ambientTemperatureSource"] = normalized
            elif isinstance(previous_ambient, dict):
                self._data["ambientTemperatureSource"] = deepcopy(previous_ambient)
            self._save()
            return deepcopy(self._data)