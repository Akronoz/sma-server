"""Queue of IoT commands pending execution by the gateway on the RPi."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STORE = Path(__file__).with_name("data") / "iot_commands.json"


@dataclass
class IotCommand:
    id: str
    device_id: str
    action: str
    created_at: str
    status: str = "pending"
    output: int | None = None
    state: bool | None = None
    detail: str = ""

    def to_public(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("output") is None:
            data.pop("output", None)
        if data.get("state") is None:
            data.pop("state", None)
        if not data.get("detail"):
            data.pop("detail", None)
        return data


class CommandStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STORE
        self._lock = threading.Lock()
        self._commands: dict[str, IotCommand] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            cmd = IotCommand(
                id=str(item.get("id", "")),
                device_id=str(item.get("device_id", "")),
                action=str(item.get("action", "")),
                created_at=str(item.get("created_at", "")),
                status=str(item.get("status", "pending")),
                output=item.get("output"),
                state=item.get("state"),
                detail=str(item.get("detail", "")),
            )
            if cmd.id:
                self._commands[cmd.id] = cmd

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [cmd.to_public() for cmd in self._commands.values()]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def enqueue(
        self,
        *,
        device_id: str,
        action: str,
        output: int | None = None,
        state: bool | None = None,
    ) -> IotCommand:
        command = IotCommand(
            id=uuid.uuid4().hex[:12],
            device_id=device_id,
            action=action,
            created_at=datetime.now(timezone.utc).isoformat(),
            output=output,
            state=state,
        )
        with self._lock:
            self._commands[command.id] = command
            self._save()
        return command

    def list_pending(self) -> list[IotCommand]:
        with self._lock:
            return [cmd for cmd in self._commands.values() if cmd.status == "pending"]

    def acknowledge(self, command_id: str, *, ok: bool, detail: str = "") -> IotCommand | None:
        with self._lock:
            command = self._commands.get(command_id)
            if command is None:
                return None
            command.status = "done" if ok else "failed"
            command.detail = detail
            self._save()
            return command