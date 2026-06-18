"""WebSocketMessageSource — filtered inbound from telegramy (contract 1).

Subscribes with events=["message"] ONLY. DM chat_ids are not known until the
first message arrives, so a chats filter would drop legitimate DMs; the
allowlist gates which messages actually get processed.

This is a thin adapter over the ``websockets`` library — the subscription
protocol belongs here, not in the application layer. The Relay depends on the
MessageSource port, never on this class.

Reconnect/backoff is deliberately NOT implemented: if telegramy is briefly
unavailable, ``websockets.connect`` raises, the Relay exits, and the process
supervisor restarts it. That is the documented MVP shutdown model (clean log +
exit 1 in main.py). If unsupervised deployment is ever needed, wrap the
connection in a reconnect-with-backoff loop here.
"""

import json
import logging
from collections.abc import AsyncGenerator

import websockets

from relaypi.core.domain.interfaces.message_source import MessageSource

logger = logging.getLogger(__name__)

# We only care about message events. callback_query is subscribed separately
# when the approval-keyboard path is built (Slice 3+).
_SUBSCRIBED_EVENTS = ["message"]


class WebSocketMessageSource(MessageSource):
    """A MessageSource backed by a telegramy WebSocket subscription."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def events(self) -> AsyncGenerator[dict, None]:
        """Connect, subscribe, and yield decoded event dicts until disconnect."""
        async with websockets.connect(self._url) as ws:
            await ws.send(
                json.dumps({"type": "subscribe", "events": _SUBSCRIBED_EVENTS})
            )
            async for raw in ws:
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("dropping non-JSON WebSocket frame")
                    continue
