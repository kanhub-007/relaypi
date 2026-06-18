"""MessageSource port — filtered inbound event stream (contract 1)."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class MessageSource(ABC):
    """A stream of raw telegramy WebSocket events, already filtered server-side."""

    @abstractmethod
    async def events(self) -> AsyncGenerator[dict, None]:
        """Yield raw event dicts. Implementations are async generators."""
        ...
