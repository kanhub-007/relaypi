"""Concurrency tests for the Relay — Scenario 4.

Asserts the two halves of the concurrency model:
  * Same chat -> serialized, in order (never two prompts on one PI at once).
  * Different chats -> concurrent (the read loop is not blocked by one turn).

Observable outcomes: the number of simultaneously in-flight prompts
(``pending``), and the order of recorded commands. No interaction assertions.
"""

import asyncio

import pytest

from hal_relay.core.application.relay import Relay
from tests.fakes.allow_all_list import AllowAllList
from tests.fakes.blocking_agent_client import BlockingAgentClient
from tests.fakes.event_helpers import msg_event
from tests.fakes.fake_message_sender import FakeMessageSender
from tests.fakes.fake_message_source import FakeMessageSource


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    """Poll ``predicate`` until it is truthy, failing after ``timeout`` seconds."""
    elapsed = 0.0
    step = 0.005
    while not predicate():
        if elapsed >= timeout:
            pytest.fail(f"condition not met within {timeout}s")
        await asyncio.sleep(step)
        elapsed += step


async def test_same_chat_messages_are_serialized_in_order():
    pi = BlockingAgentClient()
    relay = Relay(
        source=FakeMessageSource([
            msg_event("123", "koena", "first"),
            msg_event("123", "koena", "second"),
        ]),
        router=_single_client_router(pi),
        sender=FakeMessageSender(),
        allowlist=AllowAllList(),
    )

    drain_task = asyncio.create_task(relay.drain())

    # The first prompt is in flight; the second has NOT started (lock held).
    await _wait_until(lambda: len(pi.pending) >= 1)
    assert len(pi.pending) == 1
    assert pi.commands[0]["message"] == "[from=koena] first"

    # Let other tasks run; the second must still be blocked out.
    await asyncio.sleep(0)
    assert len(pi.pending) == 1

    # Release the first -> the second starts.
    pi.pending[0].set_result(None)
    await _wait_until(lambda: len(pi.pending) >= 2)
    assert pi.commands[1]["message"] == "[from=koena] second"

    pi.pending[1].set_result(None)
    await drain_task

    assert [c["message"] for c in pi.commands] == [
        "[from=koena] first",
        "[from=koena] second",
    ]


async def test_different_chats_run_concurrently():
    # A router that hands out a distinct BlockingAgentClient per chat.
    clients: dict[str, BlockingAgentClient] = {}

    class PerChatRouter:
        async def get_or_create(self, chat_id: str):
            if chat_id not in clients:
                clients[chat_id] = BlockingAgentClient()
            return clients[chat_id]

        async def stop_all(self) -> None:
            pass

    relay = Relay(
        source=FakeMessageSource([
            msg_event("123", "koena", "hello"),
            msg_event("456", "alice", "hi"),
        ]),
        router=PerChatRouter(),  # type: ignore[arg-type]
        sender=FakeMessageSender(),
        allowlist=AllowAllList(),
    )

    drain_task = asyncio.create_task(relay.drain())

    # Both chats should be in flight simultaneously (read loop not blocked).
    await _wait_until(
        lambda: len(clients) == 2
        and all(len(c.pending) >= 1 for c in clients.values())
    )

    # Release both and let the turns finish.
    clients["123"].pending[0].set_result(None)
    clients["456"].pending[0].set_result(None)
    await drain_task

    assert clients["123"].commands[0]["message"] == "[from=koena] hello"
    assert clients["456"].commands[0]["message"] == "[from=alice] hi"


def _single_client_router(client):
    class _Router:
        async def get_or_create(self, chat_id: str):
            return client

        async def stop_all(self) -> None:
            pass

    return _Router()
