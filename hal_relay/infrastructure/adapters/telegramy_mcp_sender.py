"""TelegramyMCPSender — outbound to Telegram via telegramy's MCP send tools.

Implements the MessageSender port over MCP streamable-http. The handshake
(initialize -> capture mcp-session-id -> notifications/initialized -> tools/call)
mirrors telegramy's own .pi/extensions/telegramy.ts McpHttpClient, so this
client and that extension speak the same proven protocol.

A transport seam (httpx.MockTransport in tests, the real AsyncClient in prod)
makes the HTTP boundary testable without a network.
"""

import json
import logging

import httpx

from hal_relay.core.domain.interfaces.message_sender import MessageSender

logger = logging.getLogger(__name__)

_MCP_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "hal-relay", "version": "0.1.0"}
_TOOLS_CALL_TIMEOUT = 300.0  # match telegramy's tools/call timeout


class TelegramyMCPSender(MessageSender):
    """Sends messages by calling telegramy's ``send_message`` MCP tool."""

    def __init__(
        self,
        mcp_url: str,
        timeout: float = _TOOLS_CALL_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = mcp_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._session_id: str | None = None
        self._req_id = 0

    async def send_message(self, chat_id: str, text: str) -> None:
        """Send a text message to a Telegram chat via telegramy's MCP server."""
        await self._ensure_initialized()
        result = await self._call(
            "tools/call",
            {"name": "send_message", "arguments": {"chat_id": chat_id, "text": text}},
        )
        logger.debug("send_message result for %s: %s", chat_id, result)

    async def close(self) -> None:
        """Release the HTTP connection pool."""
        await self._client.aclose()

    async def _ensure_initialized(self) -> None:
        if self._session_id is not None:
            return
        resp = await self._client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": _CLIENT_INFO,
                },
            },
            headers=self._headers(init=True),
        )
        resp.raise_for_status()
        # Per MCP spec the server waits for notifications/initialized before
        # processing requests. Commit the session id ONLY after that notification
        # succeeds — if it fails (transient 5xx, telegramy restarting), leaving
        # _session_id set would wedge the sender: every later call would skip the
        # handshake while the server never received the notification.
        session_id = resp.headers.get("mcp-session-id")
        # The server waits for this notification before processing requests; a
        # 202 Accepted is the success path. Raise on anything else so the
        # session id is NOT committed (see comment above) and the next call
        # retries the whole handshake.
        notify_resp = await self._client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers=self._headers(),
        )
        notify_resp.raise_for_status()
        self._session_id = session_id

    async def _call(self, method: str, params: dict) -> dict:
        self._req_id += 1
        resp = await self._client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": self._req_id,
                "method": method,
                "params": params,
            },
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = self._parse(resp.text)
        if "error" in data:
            raise RuntimeError(f"telegramy MCP error: {data['error']}")
        return data.get("result", {})

    def _headers(self, init: bool = False) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # The session id is returned by initialize and must be replayed thereafter.
        if self._session_id is not None and not init:
            headers["mcp-session-id"] = self._session_id
        return headers

    @staticmethod
    def _parse(text: str) -> dict:
        """FastMCP streamable-http returns SSE; plain JSON is also accepted."""
        if text.startswith("{"):
            return json.loads(text)
        for line in text.split("\n"):
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return {}
