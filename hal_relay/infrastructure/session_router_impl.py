"""PerChatSessionRouter — one PI process per chat, isolated by --session <path>.

Restarts a chat's client when its previous process has died (is_alive False),
pointing at the SAME session path so PI resumes the persisted conversation.

The subprocess-creation concern is injected as ``client_factory``: an async
callable (session_path) -> AgentClient. This is the seam that lets the router
be unit-tested with fakes (no real PI needed); the real factory (which spawns
PIRpcClient) is wired in startup/.
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from hal_relay.core.domain.interfaces.agent_client import AgentClient
from hal_relay.core.domain.interfaces.session_router import SessionRouter

logger = logging.getLogger(__name__)

ClientFactory = Callable[[str], Awaitable[AgentClient]]


class PerChatSessionRouter(SessionRouter):
    """Routes chat_id -> a live AgentClient, (re)starting as needed."""

    def __init__(self, session_root: str, client_factory: ClientFactory) -> None:
        self._root = Path(session_root)
        self._factory = client_factory
        self._clients: dict[str, AgentClient] = {}

    async def get_or_create(self, chat_id: str) -> AgentClient:
        """Return a live client for chat_id, restarting if the previous one died."""
        existing = self._clients.get(chat_id)
        if existing is not None and existing.is_alive():
            return existing

        path = self.path_for(chat_id)
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("starting PI client for chat %s at %s", chat_id, path)
        client = await self._factory(path)
        self._clients[chat_id] = client
        return client

    def path_for(self, chat_id: str) -> str:
        """Compute the session file path for a chat_id.

        Group ids are negative; '-' is replaced with 'g' to keep the filename
        filesystem-safe. The path is a pure function of chat_id (no stored map).
        """
        safe = chat_id.replace("-", "g")
        return str(self._root / f"chat_{safe}.jsonl")

    async def stop_all(self) -> None:
        """Stop every managed client and forget them."""
        for client in self._clients.values():
            await client.stop()
        self._clients.clear()
