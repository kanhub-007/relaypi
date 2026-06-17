"""Tests for PerChatSessionRouter — Scenario 3 (distinct sessions) + restart-on-dead.

Classical school: a fake client factory records the session paths it was asked
to create and returns FakeAgentClients. We assert on observable outcomes
(paths, client identity, restart behaviour) — never on interactions.
"""

from pathlib import Path

from hal_relay.infrastructure.session_router_impl import PerChatSessionRouter
from tests.fakes.fake_agent_client import FakeAgentClient


class RecordingFactory:
    """Fake client factory: records each requested session path, returns fakes."""

    def __init__(self) -> None:
        self.created_paths: list[str] = []

    async def __call__(self, session_path: str) -> FakeAgentClient:
        self.created_paths.append(session_path)
        return FakeAgentClient(reply="[ok]", alive=True)


async def test_distinct_chats_get_distinct_session_paths_and_clients():
    factory = RecordingFactory()
    router = PerChatSessionRouter(session_root="hal/sessions", client_factory=factory)

    client_a = await router.get_or_create("123")
    client_b = await router.get_or_create("456")

    # Two distinct paths, two distinct clients.
    assert factory.created_paths == [
        str(Path("hal/sessions/chat_123.jsonl")),
        str(Path("hal/sessions/chat_456.jsonl")),
    ]
    assert client_a is not client_b


async def test_repeated_chat_reuses_existing_client():
    factory = RecordingFactory()
    router = PerChatSessionRouter(session_root="hal/sessions", client_factory=factory)

    first = await router.get_or_create("123")
    second = await router.get_or_create("123")

    # Same client returned; factory only invoked once.
    assert first is second
    assert len(factory.created_paths) == 1


async def test_group_chat_id_negative_is_sanitized_in_filename():
    factory = RecordingFactory()
    router = PerChatSessionRouter(session_root="hal/sessions", client_factory=factory)

    await router.get_or_create("-100111000")

    assert factory.created_paths == [str(Path("hal/sessions/chat_g100111000.jsonl"))]


async def test_dead_client_is_restarted_on_next_access():
    factory = RecordingFactory()
    router = PerChatSessionRouter(session_root="hal/sessions", client_factory=factory)

    first = await router.get_or_create("123")
    assert first.is_alive() is True

    # Simulate a crash: the process dies.
    first._alive = False  # type: ignore[attr-defined]

    restarted = await router.get_or_create("123")

    # A new client was created at the SAME session path (PI resumes the file).
    assert restarted is not first
    assert restarted.is_alive() is True
    assert len(factory.created_paths) == 2
    assert factory.created_paths[0] == factory.created_paths[1]
