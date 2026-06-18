"""Tests for the Relay orchestrator — Scenario 1 (happy path + skip).

Black-box: we wire the Relay with in-memory fakes and assert on observable
outcomes (what was prompted, what was sent). No interaction assertions.
"""

from relaypi.core.application.relay import Relay
from relaypi.core.domain.entities.group_config import GroupConfig
from relaypi.core.domain.interfaces.session_router import SessionRouter
from relaypi.infrastructure.allowlist_config import ConfigAllowlist
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


async def test_relay_drops_non_allowlisted_senders_and_keeps_allowlisted():
    # Scenario 2 (Relay integration): only the allowlisted user is prompted.
    pi = FakeAgentClient()
    sender = FakeMessageSender()
    allowlist = ConfigAllowlist(dm_users={987654321}, groups={})
    relay = Relay(
        source=FakeMessageSource(
            [
                msg_event("1", "stranger", "hi", user_id=999),  # not allowlisted
                msg_event("2", "koena", "hi", user_id=987654321),  # allowlisted
            ]
        ),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=allowlist,
    )

    await relay.drain()

    # Only the allowlisted user's message reached PI.
    assert len(pi.commands) == 1
    assert "[from=koena]" in pi.commands[0]["message"]
    assert sender.sent == [{"chat_id": "2", "text": "[ok]"}]


async def test_relay_applies_open_and_restricted_group_modes():
    pi = FakeAgentClient()
    sender = FakeMessageSender()
    allowlist = ConfigAllowlist(
        dm_users=set(),
        groups={
            -100111000: GroupConfig(mode="open"),
            -100222000: GroupConfig(mode="restricted", members=frozenset({111222333})),
        },
    )
    relay = Relay(
        source=FakeMessageSource(
            [
                msg_event(
                    -100111000, "anyone", "hi", chat_type="group", user_id=555
                ),  # open
                msg_event(
                    -100222000, "alice", "hi", chat_type="group", user_id=111222333
                ),  # member
                msg_event(
                    -100222000, "stranger", "hi", chat_type="group", user_id=999
                ),  # not member
            ]
        ),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=allowlist,
    )

    await relay.drain()

    assert len(pi.commands) == 2


async def test_relay_routes_distinct_chats_to_distinct_sessions():
    # Scenario 3 (Relay integration): two chats -> two router lookups, one each.
    seen_chats: list[str] = []

    class RecordingRouter(SessionRouter):
        async def get_or_create(self, chat_id: str):
            seen_chats.append(chat_id)
            return FakeAgentClient(reply=f"reply-{chat_id}")

        async def stop_all(self) -> None:
            pass

    relay = Relay(
        source=FakeMessageSource(
            [
                msg_event("123", "koena", "hello"),
                msg_event("456", "alice", "hi"),
            ]
        ),
        router=RecordingRouter(),
        sender=FakeMessageSender(),
        allowlist=AllowAllList(),
    )

    await relay.drain()

    assert set(seen_chats) == {"123", "456"}
