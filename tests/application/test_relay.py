"""Tests for the Relay orchestrator — Scenario 1 (happy path + skip).

Black-box: we wire the Relay with in-memory fakes and assert on observable
outcomes (what was prompted, what was sent). No interaction assertions.
"""

import asyncio

from hal_relay.core.application.relay import Relay
from tests.fakes.allow_all_list import AllowAllList
from tests.fakes.event_helpers import msg_event
from tests.fakes.fake_agent_client import FakeAgentClient
from tests.fakes.fake_message_sender import FakeMessageSender
from tests.fakes.fake_message_source import FakeMessageSource
from tests.fakes.fake_router import FakeRouter


async def test_relay_formats_with_username_and_delivers_reply():
    # Arrange — a fake PI that replies "BTC looks bullish", recording prompts.
    pi = FakeAgentClient(reply="BTC looks bullish")
    sender = FakeMessageSender()
    relay = Relay(
        source=FakeMessageSource([msg_event("123", "koena", "analyze BTC")]),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=AllowAllList(),
    )

    # Act
    await relay.drain()

    # Assert — the prompt was formatted with the username; the reply was sent.
    assert pi.commands == [{"type": "prompt", "message": "[from=koena] analyze BTC"}]
    assert sender.sent == [{"chat_id": "123", "text": "BTC looks bullish"}]


async def test_relay_skips_non_message_events():
    pi = FakeAgentClient()
    sender = FakeMessageSender()
    relay = Relay(
        source=FakeMessageSource([{"callback_query": {"id": "abc"}}]),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=AllowAllList(),
    )

    await relay.drain()

    # No prompt sent, no reply sent.
    assert pi.commands == []
    assert sender.sent == []
