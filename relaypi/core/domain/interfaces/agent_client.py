"""AgentClient port — one PI RPC subprocess (contract 2).

Serialized externally per-chat by the Relay: never call prompt_and_collect on
a client whose previous turn has not finished.
"""

from abc import ABC, abstractmethod


class AgentClient(ABC):
    """A single PI conversation endpoint."""

    @abstractmethod
    async def prompt_and_collect(self, message: str) -> str:
        """Send a prompt, await turn completion, return final assistant text."""
        ...

    @abstractmethod
    async def abort(self) -> None:
        """Cancel the current turn (used on timeout). Warm process preserved."""
        ...

    @abstractmethod
    def is_alive(self) -> bool:
        """True if the underlying subprocess is still running."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Tear down the subprocess."""
        ...
