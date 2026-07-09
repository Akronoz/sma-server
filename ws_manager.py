"""WebSocket connections from plant gateways (command push)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("backend.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, gateway_id: str) -> None:
        await websocket.accept()
        self.active_connections[gateway_id] = websocket
        logger.info("Gateway %s connected via WS", gateway_id)

    def disconnect(self, gateway_id: str) -> None:
        self.active_connections.pop(gateway_id, None)
        logger.info("Gateway %s disconnected", gateway_id)

    async def send_command(self, gateway_id: str, command: dict[str, Any]) -> bool:
        websocket = self.active_connections.get(gateway_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json({"type": "command", "payload": command})
            logger.info("Command %s pushed via WS to gateway %s", command.get("id"), gateway_id)
            return True
        except Exception as exc:
            logger.warning("Failed to send WS command to %s: %s", gateway_id, exc)
            self.disconnect(gateway_id)
            return False

    def is_connected(self, gateway_id: str) -> bool:
        return gateway_id in self.active_connections


ws_manager = ConnectionManager()