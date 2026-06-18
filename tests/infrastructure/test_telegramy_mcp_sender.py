"""Tests for TelegramyMCPSender — MCP-over-streamable-http (contract 3).

The MCP handshake (initialize -> capture mcp-session-id -> notifications/
initialized -> tools/call) is the real protocol telegramy's own extension uses.
We verify it via httpx.MockTransport, a library transport seam that gives real
HTTP request/response semantics without a network — analogous to the
StreamTransport seam used for PIRpcClient.

Asserts on observable outcomes: sent messages reach the sender; the correct
MCP method/arguments are issued; the session id is captured and replayed.
"""

import json

import httpx
import pytest

from hal_relay.infrastructure.adapters.telegramy_mcp_sender import TelegramyMCPSender

MCP_URL = "http://telegramy.test/mcp"


def _mock_transport_factory(captured: dict) -> httpx.MockTransport:
    """Build a MockTransport that speaks the MCP streamable-http subset."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured["requests"].append(body)
        captured["headers"].append(dict(request.headers))

        # initialize -> return a session id header.
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                headers={"mcp-session-id": "sess-123"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}},
            )
        # notifications/initialized -> accepted, no body.
        if body.get("method") == "notifications/initialized":
            return httpx.Response(202)
        # tools/call -> return a text content block.
        if body.get("method") == "tools/call":
            assert (
                request.headers.get("mcp-session-id") == "sess-123"
            ), "session id must be replayed on subsequent requests"
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"content": [{"type": "text", "text": "sent"}]},
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _make_sender(captured: dict) -> TelegramyMCPSender:
    return TelegramyMCPSender(
        mcp_url=MCP_URL,
        transport=_mock_transport_factory(captured),
    )


async def test_send_message_runs_full_mcp_handshake_then_tools_call():
    captured: dict = {"requests": [], "headers": []}
    sender = _make_sender(captured)
    try:
        await sender.send_message("123", "hello")
    finally:
        await sender.close()

    methods = [r["method"] for r in captured["requests"]]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]

    # The actual send is a tools/call with the right tool name + arguments.
    tools_call = captured["requests"][-1]
    assert tools_call["method"] == "tools/call"
    assert tools_call["params"]["name"] == "send_message"
    assert tools_call["params"]["arguments"] == {"chat_id": "123", "text": "hello"}


async def test_handshake_runs_only_once_across_multiple_sends():
    captured: dict = {"requests": [], "headers": []}
    sender = _make_sender(captured)
    try:
        await sender.send_message("1", "a")
        await sender.send_message("2", "b")
        await sender.send_message("3", "c")
    finally:
        await sender.close()

    methods = [r["method"] for r in captured["requests"]]
    # One initialize + one initialized notification, then three tools/calls.
    assert methods.count("initialize") == 1
    assert methods.count("notifications/initialized") == 1
    assert methods.count("tools/call") == 3


async def test_mcp_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                headers={"mcp-session-id": "s"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
            )
        if body.get("method") == "notifications/initialized":
            return httpx.Response(202)
        # tools/call returns an MCP-level error.
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32602, "message": "missing chat_id"},
            },
        )

    sender = TelegramyMCPSender(MCP_URL, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match="telegramy MCP error"):
            await sender.send_message("123", "hi")
    finally:
        await sender.close()


async def test_partial_handshake_failure_retries_full_handshake_on_next_call():
    # C1: if the notifications/initialized POST fails, the sender must NOT keep
    # the session id (which would skip the handshake forever). The next call
    # must re-run initialize from scratch.
    attempts = {"init_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if body.get("method") == "initialize":
            attempts["init_count"] += 1
            return httpx.Response(
                200,
                headers={"mcp-session-id": "sess"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
            )
        if body.get("method") == "notifications/initialized":
            # First time: fail (e.g. telegramy briefly 5xx'd). Second time: ok.
            if attempts["init_count"] == 1:
                return httpx.Response(500, text="transient")
            return httpx.Response(202)
        # tools/call
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            },
        )

    sender = TelegramyMCPSender(MCP_URL, transport=httpx.MockTransport(handler))
    try:
        # First send fails during the notification step.
        with pytest.raises(httpx.HTTPStatusError):
            await sender.send_message("123", "first")
        # Sender did NOT commit the session id.
        assert sender._session_id is None  # type: ignore[attr-defined]

        # Second send retries the FULL handshake and succeeds.
        await sender.send_message("123", "second")
        assert attempts["init_count"] == 2  # initialize ran twice
    finally:
        await sender.close()
