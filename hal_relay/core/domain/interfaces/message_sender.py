"""MessageSender port — outbound send to Telegram via telegramy MCP (contract 3)."""

from abc import ABC, abstractmethod


class MessageSender(ABC):
    """Sends messages back to the user via telegramy's send tools."""

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> None:
        """Send a text message to a chat."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying client resources (e.g. HTTP connection pool)."""
        ...
