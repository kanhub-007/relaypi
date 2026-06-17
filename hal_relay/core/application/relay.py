"""Relay — the binding use case.

Pipeline: trust -> route -> format -> prompt -> capture -> send.

Concurrency model (see 03-domain.md):
  * Per-message asyncio task — the WebSocket read loop never blocks on a turn.
  * Per-chat asyncio.Lock — turns on one PI process never overlap.
"""

import asyncio
import logging

from hal_relay.core.application.format_prompt import format_prompt
from hal_relay.core.application.parse import parse_inbound
from hal_relay.core.domain.entities.inbound_message import InboundMessage
from hal_relay.core.domain.interfaces.allowlist import Allowlist
from hal_relay.core.domain.interfaces.message_sender import MessageSender
from hal_relay.core.domain.interfaces.message_source import MessageSource
from hal_relay.core.domain.interfaces.session_router import SessionRouter

logger = logging.getLogger(__name__)


class Relay:
    """Glue between a MessageSource, a SessionRouter, a MessageSender, and an Allowlist."""

    def __init__(
        self,
        source: MessageSource,
        router: SessionRouter,
        sender: MessageSender,
        allowlist: Allowlist,
    ) -> None:
        self._source = source
        self._router = router
        self._sender = sender
        self._allowlist = allowlist
        self._chat_locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        """Read the source without blocking; dispatch each message as its own task."""
        async for event in self._source.events():
            msg = parse_inbound(event)
            if msg is None:
                continue
            if not self._allowlist.allows(msg):
                logger.info(
                    "dropped message from %s in chat %s",
                    msg.sender_user_id,
                    msg.chat_id,
                )
                continue
            task = asyncio.create_task(self._handle(msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _handle(self, msg: InboundMessage) -> None:
        # Per-chat serialization: never prompt a streaming PI.
        lock = self._chat_locks.setdefault(msg.chat_id, asyncio.Lock())
        async with lock:
            try:
                client = await self._router.get_or_create(msg.chat_id)
                prompt = format_prompt(msg)
                text = await client.prompt_and_collect(prompt.text)
                await self._sender.send_message(msg.chat_id, text)
            except Exception:
                # Never let one message's failure kill the relay or leave the
                # user in silence. Report the error back to the chat.
                logger.exception("failed to handle message in chat %s", msg.chat_id)
                try:
                    await self._sender.send_message(
                        msg.chat_id,
                        "⚠️ Something went wrong processing that. Try again.",
                    )
                except Exception:
                    logger.exception("also failed to send error reply")

    async def drain(self) -> None:
        """Run to completion against a finite source (test helper)."""
        await self.run()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        """Graceful shutdown: wait for in-flight turns, stop clients, close sender."""
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._router.stop_all()
        await self._sender.close()
