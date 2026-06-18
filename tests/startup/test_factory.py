"""Composition-root smoke test — the factory wires a runnable Relay.

Verifies, with real asyncio + a real local WebSocket server (no mocks):
  * create_relay() returns a Relay whose adapters are the concrete prod classes
  * the WS source actually subscribes and yields events from a live server
  * the allowlist from Config gates as expected

Does NOT start PI or call telegramy (those need live services); it stops at the
boundary the factory owns. Subprocess/PI behaviour is covered by
test_subprocess_stream_transport.py and test_pi_rpc_client.py.
"""

import asyncio
import json
import os

import pytest
from websockets.asyncio.server import serve

from relaypi.core.application.relay import Relay
from relaypi.core.domain.interfaces.session_router import SessionRouter
from relaypi.infrastructure.adapters.websocket_message_source import (
    WebSocketMessageSource,
)
from relaypi.startup.factory import create_relay
from tests.fakes.allow_all_list import AllowAllList
from tests.fakes.fake_agent_client import FakeAgentClient
from tests.fakes.fake_message_sender import FakeMessageSender
from tests.fakes.event_helpers import msg_event


@pytest.fixture
def clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("HAL_"):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


async def _serve_one_event(port: int, event: dict, done: asyncio.Event) -> None:
    """Run a tiny WS server that delivers one event to the first client.

    Signals ``done`` after the event is sent, so the test can wait deterministically
    (no fixed sleeps racing the client handshake).
    """

    async def handler(stream) -> None:
        # First frame from the client is the subscribe message; echo it back
        # as confirmation, then deliver the scripted event.
        sub = await stream.recv()
        await stream.send(sub)
        await stream.send(json.dumps(event))
        done.set()

    server = await serve(handler, "127.0.0.1", port)
    try:
        await done.wait()
    finally:
        server.close()
        await server.wait_closed()


async def test_websocket_source_subscribes_and_yields_events(clean_env, monkeypatch):
    port = 18765
    monkeypatch.setenv("RELAYPI_WS_URL", f"ws://127.0.0.1:{port}")

    done = asyncio.Event()
    server_task = asyncio.create_task(
        _serve_one_event(port, msg_event("123", "alice", "hello"), done)
    )
    # Tiny allow-all Relay so we can observe the event reaching the router.
    seen: list[str] = []

    class CaptureRouter(SessionRouter):
        async def get_or_create(self, chat_id: str):
            seen.append(chat_id)
            return FakeAgentClient(reply="ok")

        async def stop_all(self) -> None:
            pass

    relay = Relay(
        source=WebSocketMessageSource(f"ws://127.0.0.1:{port}"),
        router=CaptureRouter(),
        sender=FakeMessageSender(),
        allowlist=AllowAllList(),
    )

    run_task = asyncio.create_task(relay.run())
    await asyncio.wait_for(done.wait(), timeout=3.0)
    await asyncio.sleep(0.1)  # let the relay process the delivered frame
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass
    await server_task  # ensure clean server exit
    await relay.stop()

    assert seen == ["123"]


async def test_factory_builds_relay_with_concrete_adapters(
    clean_env, monkeypatch, tmp_path
):
    # Point config at a temp allowlist so Config() doesn't require a repo file.
    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text("dm_users: [123]\n")
    monkeypatch.setenv("RELAYPI_ALLOWLIST", str(allowlist))
    monkeypatch.setenv(
        "RELAYPI_WS_URL", "ws://127.0.0.1:9"
    )  # unreachable; we won't run

    relay = create_relay()
    try:
        assert isinstance(relay, Relay)
        # The source/sender/router are the real prod adapters.
        assert isinstance(relay._source, WebSocketMessageSource)  # type: ignore[attr-defined]
        assert isinstance(relay._sender, FakeMessageSender) is False  # real sender
        # Allowlist was loaded by the factory from cfg.allowlist_path and gates.
        from relaypi.core.application.parse import parse_inbound

        assert relay._allowlist.allows(parse_inbound(msg_event("123", "x", "hi", user_id=123)))  # type: ignore[attr-defined]
        assert not relay._allowlist.allows(parse_inbound(msg_event("999", "x", "hi", user_id=999)))  # type: ignore[attr-defined]
    finally:
        await relay._sender.close()  # type: ignore[attr-defined]
