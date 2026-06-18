"""WebSocketMessageSource — filtered inbound from telegramy (contract 1).

Subscribes with events=["message"] ONLY. DM chat_ids are not known until the
first message arrives, so a chats filter would drop legitimate DMs; the
allowlist gates which messages actually get processed.

This is a thin adapter over the ``websockets`` library — the subscription
protocol and reconnect/retry behaviour belong here, not in the application
layer. The Relay depends on the MessageSource port, never on this class.
"""

import json
import logging
from collections.abc import AsyncIterator

import websockets

logger = logging.getLogger(__name__)

# We only care about message events. callback_query is subscribed separately
# when the approval-keyboard path is built (Slice 3+).
_SUBSCRIBED_EVENTS = ["message"]


class WebSocketMessageSource:
    """A MessageSource backed by a telegramy WebSocket subscription."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def events(self) -> AsyncIterator[dict]:
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
