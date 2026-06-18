"""Scenario: PI handles /reset command (Slice 2, Should).

MVP decision (per 02-scenarios.md): the relay does NOT intercept commands. It
forwards ``/reset`` as an ordinary prompt, and PI's system prompt handles it.
This test locks that behaviour so a future interception feature doesn't
silently regress the simple-forward path until it's deliberately switched on.
"""

from relaypi.core.application.relay import Relay
from tests.fakes.allow_all_list import AllowAllList
from tests.fakes.event_helpers import msg_event
from tests.fakes.fake_agent_client import FakeAgentClient
from tests.fakes.fake_message_sender import FakeMessageSender
from tests.fakes.fake_message_source import FakeMessageSource
from tests.fakes.fake_router import FakeRouter


async def test_reset_command_is_forwarded_as_a_prompt():
    pi = FakeAgentClient(reply="Session reset")
    sender = FakeMessageSender()
    relay = Relay(
        source=FakeMessageSource([msg_event("123", "alice", "/reset")]),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=AllowAllList(),
    )

    await relay.drain()

    # Forwarded verbatim with the display prefix — no interception, no new_session.
    assert pi.commands == [{"type": "prompt", "message": "[from=alice] /reset"}]
    assert sender.sent == [{"chat_id": "123", "text": "Session reset"}]
