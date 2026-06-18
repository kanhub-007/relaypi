"""Lifecycle tests for the Relay — H1 (one-shot run/drain) and H2 (cooperative stop).

Black-box: assert on observable outcomes (what was dispatched, whether run
re-enters). No interaction assertions.
"""

import pytest

from relaypi.core.application.relay import Relay
from tests.fakes.allow_all_list import AllowAllList
from tests.fakes.event_helpers import msg_event
from tests.fakes.fake_agent_client import FakeAgentClient
from tests.fakes.fake_message_sender import FakeMessageSender
from tests.fakes.fake_message_source import FakeMessageSource
from tests.fakes.fake_router import FakeRouter


async def test_run_rejects_double_start():
    # H1: run()/drain() are one-shot. A second call must raise rather than
    # silently re-iterate the source (which would double-process events).
    pi = FakeAgentClient(reply="r")
    relay = Relay(
        FakeMessageSource([msg_event("123", "alice", "hi")]),
        FakeRouter(pi),
        FakeMessageSender(),
        AllowAllList(),
    )
    await relay.drain()

    with pytest.raises(RuntimeError, match="already started"):
        await relay.run()


async def test_stop_prevents_dispatch_when_set_before_run_pulls():
    # H2: the cooperative stop flag is checked at the TOP of the loop, before
    # pulling. Set before run() starts -> nothing is dispatched, even though the
    # source has events.
    #
    # Note on scope: this flag prevents NEW pulls once observed. An event already
    # mid-pull (loop blocked inside __anext__ when stop is called) will still be
    # processed; hard interruption of a blocked WebSocket read relies on task
    # cancellation at asyncio shutdown, which is the documented MVP shutdown model.
    pi = FakeAgentClient(reply="r")
    relay = Relay(
        FakeMessageSource(
            [msg_event("1", "alice", "hi"), msg_event("2", "alice", "hi")]
        ),
        FakeRouter(pi),
        FakeMessageSender(),
        AllowAllList(),
    )
    relay._stopping = True  # type: ignore[attr-defined]

    await relay.run()

    assert pi.commands == []  # nothing dispatched


async def test_stop_is_safe_before_run_starts():
    relay = Relay(
        FakeMessageSource([]),
        FakeRouter(FakeAgentClient()),
        FakeMessageSender(),
        AllowAllList(),
    )
    await relay.stop()  # no raise, no dispatch
    # And run still works afterwards (stop didn't flip _started).
    await relay.drain()
