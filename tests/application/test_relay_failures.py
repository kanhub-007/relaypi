"""Failure tests for the Relay — Scenario 6.

Black-box: wire the Relay with fakes that raise, assert the observable outcomes
(error reply sent / not sent, relay survived, subsequent message worked). The
Relay must never crash and never leave the user in silence when PI fails.
"""

from hal_relay.core.application.relay import Relay
from tests.fakes.allow_all_list import AllowAllList
from tests.fakes.event_helpers import msg_event
from tests.fakes.fake_agent_client import FakeAgentClient
from tests.fakes.fake_message_sender import FakeMessageSender
from tests.fakes.fake_message_source import FakeMessageSource
from tests.fakes.fake_router import FakeRouter


class ExplodingAgentClient(FakeAgentClient):
    """A client whose prompt always raises."""

    def __init__(self, message: str = "PI rejected prompt: bad input") -> None:
        super().__init__()
        self._boom = message

    async def prompt_and_collect(self, message: str) -> str:
        self.commands.append({"type": "prompt", "message": message})
        raise RuntimeError(self._boom)


async def test_pi_failure_yields_error_reply_not_crash():
    pi = ExplodingAgentClient()
    sender = FakeMessageSender()
    relay = Relay(
        source=FakeMessageSource([msg_event("123", "koena", "oops")]),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=AllowAllList(),
    )

    await relay.drain()  # must not raise

    assert len(sender.sent) == 1
    assert sender.sent[0]["chat_id"] == "123"
    assert "wrong" in sender.sent[0]["text"].lower()


async def test_total_sender_outage_does_not_kill_relay():
    class DeadSender(FakeMessageSender):
        async def send_message(self, chat_id: str, text: str) -> None:
            raise RuntimeError("telegramy unreachable")

    pi = FakeAgentClient(reply="hi")
    relay = Relay(
        source=FakeMessageSource([msg_event("123", "koena", "hello")]),
        router=FakeRouter(pi),
        sender=DeadSender(),
        allowlist=AllowAllList(),
    )

    # Neither the normal reply nor the error reply can be sent, but the relay
    # survives and drain() completes.
    await relay.drain()


async def test_failure_releases_lock_so_next_message_works():
    # First call raises, second succeeds — proving the per-chat lock was
    # released despite the exception (otherwise the second would deadlock).
    class RaiseOnceThenOk(FakeAgentClient):
        def __init__(self) -> None:
            super().__init__()
            self._calls = 0

        async def prompt_and_collect(self, message: str) -> str:
            self._calls += 1
            self.commands.append({"type": "prompt", "message": message})
            if self._calls == 1:
                raise RuntimeError("transient")
            return "recovered"

    pi = RaiseOnceThenOk()
    sender = FakeMessageSender()
    relay = Relay(
        source=FakeMessageSource([
            msg_event("123", "koena", "first"),
            msg_event("123", "koena", "second"),
        ]),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=AllowAllList(),
    )

    await relay.drain()

    # First -> error reply; second -> real reply. Lock was released between them.
    assert len(sender.sent) == 2
    assert "wrong" in sender.sent[0]["text"].lower()
    assert sender.sent[1] == {"chat_id": "123", "text": "recovered"}
