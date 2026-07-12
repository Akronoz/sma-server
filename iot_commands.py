"""Queue of IoT commands pending execution by the gateway on the RPi."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from json_io import atomic_write_json, read_json

logger = logging.getLogger("backend.commands")

DEFAULT_STORE = Path(__file__).with_name("data") / "iot_commands.json"

# Pending commands older than this are not delivered (stale after gateway downtime).
DEFAULT_PENDING_TTL_S = 900  # 15 min
# Terminal commands (done/failed/expired) older than this are purged from disk.
DEFAULT_TERMINAL_RETENTION_S = 86_400  # 24 h
# Hard cap to avoid unbounded growth if clocks/retention misbehave.
DEFAULT_MAX_COMMANDS = 500


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _parse_iso(ts: str) -> datetime | None:
    text = (ts or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


@dataclass
class IotCommand:
    id: str
    device_id: str
    action: str
    created_at: str
    status: str = "pending"
    output: int | None = None
    state: bool | None = None
    url: str = ""
    detail: str = ""
    updated_at: str = ""

    def to_public(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("output") is None:
            data.pop("output", None)
        if data.get("state") is None:
            data.pop("state", None)
        if not data.get("url"):
            data.pop("url", None)
        if not data.get("detail"):
            data.pop("detail", None)
        if not data.get("updated_at"):
            data.pop("updated_at", None)
        return data


class CommandStore:
    def __init__(
        self,
        path: Path | None = None,
        *,
        pending_ttl_s: int | None = None,
        terminal_retention_s: int | None = None,
        max_commands: int | None = None,
    ) -> None:
        self.path = path or DEFAULT_STORE
        self.pending_ttl_s = (
            pending_ttl_s
            if pending_ttl_s is not None
            else _env_int("IOT_COMMAND_PENDING_TTL_S", DEFAULT_PENDING_TTL_S)
        )
        self.terminal_retention_s = (
            terminal_retention_s
            if terminal_retention_s is not None
            else _env_int("IOT_COMMAND_RETENTION_S", DEFAULT_TERMINAL_RETENTION_S)
        )
        self.max_commands = (
            max_commands
            if max_commands is not None
            else _env_int("IOT_COMMAND_MAX", DEFAULT_MAX_COMMANDS)
        )
        self._lock = threading.Lock()
        self._commands: dict[str, IotCommand] = {}
        self._load()

    def _load(self) -> None:
        raw = read_json(self.path, default=None)
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
                url=str(item.get("url", "")),
                detail=str(item.get("detail", "")),
                updated_at=str(item.get("updated_at", "")),
            )
            if cmd.id:
                self._commands[cmd.id] = cmd

    def _save(self) -> None:
        payload = [cmd.to_public() for cmd in self._commands.values()]
        atomic_write_json(self.path, payload)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _touch(self, command: IotCommand) -> None:
        command.updated_at = self._now().isoformat()

    def _maintain_locked(self) -> bool:
        """Expire stale pending and purge old terminal commands. Caller holds lock."""
        now = self._now()
        changed = False

        if self.pending_ttl_s > 0:
            ttl = timedelta(seconds=self.pending_ttl_s)
            for cmd in list(self._commands.values()):
                if cmd.status != "pending":
                    continue
                created = _parse_iso(cmd.created_at)
                if created is None:
                    created = now
                if now - created > ttl:
                    cmd.status = "expired"
                    cmd.detail = cmd.detail or f"expired after {self.pending_ttl_s}s"
                    self._touch(cmd)
                    changed = True
                    logger.info(
                        "Command %s expired (device=%s action=%s age>%ss)",
                        cmd.id,
                        cmd.device_id,
                        cmd.action,
                        self.pending_ttl_s,
                    )

        if self.terminal_retention_s > 0:
            retain = timedelta(seconds=self.terminal_retention_s)
            for cmd_id, cmd in list(self._commands.items()):
                if cmd.status == "pending":
                    continue
                ref = _parse_iso(cmd.updated_at) or _parse_iso(cmd.created_at) or now
                if now - ref > retain:
                    del self._commands[cmd_id]
                    changed = True

        if self.max_commands > 0 and len(self._commands) > self.max_commands:
            # Drop oldest terminal first, then oldest pending.
            ordered = sorted(
                self._commands.values(),
                key=lambda c: (
                    0 if c.status == "pending" else 1,
                    _parse_iso(c.created_at) or datetime.min.replace(tzinfo=timezone.utc),
                ),
            )
            overflow = len(self._commands) - self.max_commands
            for cmd in ordered:
                if overflow <= 0:
                    break
                if cmd.status == "pending" and len(
                    [c for c in self._commands.values() if c.status == "pending"]
                ) <= 1:
                    # Keep at least the newest pending when possible.
                    continue
                if cmd.id in self._commands:
                    del self._commands[cmd.id]
                    overflow -= 1
                    changed = True

        return changed

    def enqueue(
        self,
        *,
        device_id: str,
        action: str,
        output: int | None = None,
        state: bool | None = None,
        url: str | None = None,
    ) -> IotCommand:
        now_iso = self._now().isoformat()
        command = IotCommand(
            id=uuid.uuid4().hex[:12],
            device_id=device_id,
            action=action,
            created_at=now_iso,
            updated_at=now_iso,
            output=output,
            state=state,
            url=(url or "").strip(),
        )
        with self._lock:
            self._maintain_locked()
            # Supersede older pending commands for the same target (avoid backlog of toggles).
            for existing in list(self._commands.values()):
                if existing.status != "pending":
                    continue
                if existing.device_id != device_id or existing.action != action:
                    continue
                if action in {"set_output", "release_output"} and existing.output != output:
                    continue
                existing.status = "superseded"
                existing.detail = f"replaced by {command.id}"
                self._touch(existing)
            self._commands[command.id] = command
            self._save()
        return command

    def list_pending(self) -> list[IotCommand]:
        with self._lock:
            changed = self._maintain_locked()
            if changed:
                self._save()
            return [cmd for cmd in self._commands.values() if cmd.status == "pending"]

    def acknowledge(self, command_id: str, *, ok: bool, detail: str = "") -> IotCommand | None:
        with self._lock:
            self._maintain_locked()
            command = self._commands.get(command_id)
            if command is None:
                return None
            if command.status != "pending":
                # Idempotent ack for already finished commands.
                return command
            command.status = "done" if ok else "failed"
            command.detail = detail
            self._touch(command)
            self._save()
            return command
