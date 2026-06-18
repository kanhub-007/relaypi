"""FakeRouter — returns one shared AgentClient for every chat.

Used when a test doesn't care about per-chat isolation. Tests that do care
define an inline fake router (see test_distinct_chats_get_distinct_sessions).
"""

from relaypi.core.domain.interfaces.agent_client import AgentClient


class FakeRouter:
    def __init__(self, client: AgentClient) -> None:
        self._client = client

    async def get_or_create(self, chat_id: str) -> AgentClient:
        return self._client

    async def stop_all(self) -> None:
        await self._client.stop()
