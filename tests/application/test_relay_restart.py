"""Scenario: Relay survives PI restart (Slice 2, Should) — integration.

End-to-end: a chat's PI subprocess crashes mid-turn. The Relay must (a) send an
error reply instead of hanging, and (b) transparently restart the client for
that chat on the next message, resuming at the same session path. Other chats
are untouched.

Uses the real PIRpcClient (not a fake) over a FakeStreamTransport so the
protocol's crash path is exercised honestly.
"""

from relaypi.core.application.relay import Relay
from relaypi.infrastructure.adapters.pi_rpc_client import PIRpcClient
from relaypi.infrastructure.session_router_impl import PerChatSessionRouter
from tests.fakes.allow_all_list import AllowAllList
from tests.fakes.event_helpers import msg_event
from tests.fakes.fake_message_sender import FakeMessageSender
from tests.fakes.fake_message_source import FakeMessageSource
from tests.fakes.fake_stream_transport import FakeStreamTransport

_PROMPT_ACK = {"type": "response", "id": 1, "command": "prompt", "success": True}
_AGENT_END = {"type": "agent_end", "messages": []}
_LAST_TEXT = {
    "type": "response",
    "id": 2,
    "command": "get_last_assistant_text",
    "success": True,
    "data": {"text": "recovered"},
}


class CrashThenOkFactory:
    """First client crashes mid-turn; the restarted client succeeds."""

    def __init__(self) -> None:
        self.transports: list[FakeStreamTransport] = []
        self.created_paths: list[str] = []
        self._calls = 0

    async def __call__(self, session_path: str) -> PIRpcClient:
        self._calls += 1
        self.created_paths.append(session_path)
        transport = FakeStreamTransport()
        self.transports.append(transport)
        if self._calls == 1:
            # Crash immediately after the prompt is accepted.
            transport.script_response(1, [_PROMPT_ACK])
            transport.script_eof_after(1)
        else:
            transport.script_response(1, [_PROMPT_ACK, _AGENT_END])
            transport.script_response(2, [_LAST_TEXT])
        client = PIRpcClient(transport=transport, turn_timeout=2.0, abort_timeout=1.0)
        await client.start()
        return client


async def test_crashed_chat_recovers_on_next_message_and_other_chats_unaffected():
    factory = CrashThenOkFactory()
    router = PerChatSessionRouter(session_root="hal/sessions", client_factory=factory)
    sender = FakeMessageSender()
    relay = Relay(
        source=FakeMessageSource(
            [
                msg_event("123", "alice", "first"),  # PI crashes mid-turn
                msg_event("123", "alice", "second"),  # restart -> succeeds
                msg_event("456", "alice", "hello"),  # other chat, unaffected
            ]
        ),
        router=router,
        sender=sender,
        allowlist=AllowAllList(),
    )

    await relay.drain()

    # Chat 123: error reply (crash), then "recovered" (restart succeeded).
    chat_123 = [s for s in sender.sent if s["chat_id"] == "123"]
    assert len(chat_123) == 2
    assert "wrong" in chat_123[0]["text"].lower()
    assert chat_123[1]["text"] == "recovered"

    # The restarted client reused the SAME session path (PI resumes the file).
    paths_123 = [p for p in factory.created_paths if p.endswith("chat_123.jsonl")]
    assert len(paths_123) == 2
    assert paths_123[0] == paths_123[1]

    # Chat 456 was served by a separate, untouched client.
    assert any(s["chat_id"] == "456" for s in sender.sent)
    assert len([p for p in factory.created_paths if p.endswith("chat_456.jsonl")]) == 1
