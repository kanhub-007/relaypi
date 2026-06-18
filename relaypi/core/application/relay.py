"""Relay — the binding use case.

Pipeline: trust -> route -> format -> prompt -> capture -> send.

Concurrency model (see 03-domain.md):
  * Per-message asyncio task — the WebSocket read loop never blocks on a turn.
  * Per-chat asyncio.Lock — turns on one PI process never overlap.
"""

import asyncio
import logging

from relaypi.core.application.format_prompt import format_prompt
from relaypi.core.application.parse import parse_inbound
from relaypi.core.application.presenter import Presenter
from relaypi.core.domain.agent_error import AgentError
from relaypi.core.domain.entities.inbound_message import InboundMessage
from relaypi.core.domain.entities.outbound_reply import OutboundReply
from relaypi.core.domain.interfaces.allowlist import Allowlist
from relaypi.core.domain.interfaces.message_sender import MessageSender
from relaypi.core.domain.interfaces.message_source import MessageSource
from relaypi.core.domain.interfaces.session_router import SessionRouter

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
        self._started = False  # H1: run()/drain() are one-shot
        self._stopping = (
            False  # H2: cooperative stop signal checked before each dispatch
        )

    async def run(self) -> None:
        """Read the source without blocking; dispatch each message as its own task.

        One-shot: calling run() (or drain()) twice raises — re-iterating a
        finite fake source or re-subscribing a live WebSocket would silently
        double-process. Cooperative shutdown: stop() sets _stopping, and the
        loop checks it before pulling each event so no new work is dispatched
        after stop (hard interruption of a blocked read still relies on task
        cancellation at asyncio shutdown).
        """
        if self._started:
            raise RuntimeError("Relay already started")
        self._started = True
        it = self._source.events()
        try:
            while not self._stopping:
                try:
                    event = await it.__anext__()
                except StopAsyncIteration:
                    break
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
        finally:
            # Release the async generator (lets the WS connection close promptly).
            await it.aclose()

    async def _handle(self, msg: InboundMessage) -> None:
        # Per-chat serialization: never prompt a streaming PI.
        lock = self._chat_locks.setdefault(msg.chat_id, asyncio.Lock())
        async with lock:
            try:
                client = await self._router.get_or_create(msg.chat_id)
                prompt = format_prompt(msg)
                text = await client.prompt_and_collect(prompt.text)
                await self._sender.send_message(
                    OutboundReply(chat_id=msg.chat_id, text=text)
                )
            except AgentError as exc:
                # Expected operational failure (PI down/rejected/timed out).
                # Log at WARNING (operational, not a bug) and tell the user.
                logger.warning("agent failure in chat %s: %s", msg.chat_id, exc)
                await self._safe_send_error(msg.chat_id)
            except Exception:
                # Unexpected (a programming bug). Log the full traceback so it
                # surfaces, and still tell the user something went wrong — but
                # never let one message's failure kill the relay.
                logger.exception(
                    "unexpected error handling message in chat %s", msg.chat_id
                )
                await self._safe_send_error(msg.chat_id)

    async def _safe_send_error(self, chat_id: str) -> None:
        """Best-effort error reply; never escalates if the sender is also down."""
        try:
            await self._sender.send_message(
                OutboundReply(chat_id=chat_id, text=Presenter.ERROR_REPLY_TEXT)
            )
        except Exception:
            logger.exception("also failed to send error reply")

    async def drain(self) -> None:
        """Run to completion against a finite source (test helper). One-shot."""
        await self.run()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        """Graceful shutdown: signal the loop, wait for in-flight turns, close deps."""
        self._stopping = True
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._router.stop_all()
        await self._sender.close()
