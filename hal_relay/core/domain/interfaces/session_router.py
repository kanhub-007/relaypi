"""SessionRouter port — routes chat_id to a live AgentClient."""

from abc import ABC, abstractmethod

from hal_relay.core.domain.interfaces.agent_client import AgentClient


class SessionRouter(ABC):
    """Maps a chat_id to an AgentClient, (re)starting PI as needed."""

    @abstractmethod
    async def get_or_create(self, chat_id: str) -> AgentClient:
        """Return a live client for the chat, starting/restarting PI if needed."""
        ...

    @abstractmethod
    async def stop_all(self) -> None:
        """Tear down all managed clients."""
        ...
