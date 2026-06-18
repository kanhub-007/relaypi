"""MessageSender port — outbound send to Telegram via telegramy MCP (contract 3)."""

from abc import ABC, abstractmethod

from relaypi.core.domain.entities.outbound_reply import OutboundReply


class MessageSender(ABC):
    """Sends messages back to the user via telegramy's send tools."""

    @abstractmethod
    async def send_message(self, reply: OutboundReply) -> None:
        """Send a text message to a chat."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying client resources (e.g. HTTP connection pool)."""
        ...
