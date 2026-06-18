"""parse_inbound — extract an InboundMessage from a telegramy WS event.

Pure function: no I/O, no globals. Returns None for non-message events, empty
text, or messages whose sender id is missing/invalid — such messages can never
be allowlisted, so dropping them here is fail-closed. Bad input is logged via
the module logger so a malformed feed is observable (not silently dropped).
"""

import logging

from relaypi.core.domain.entities.inbound_message import InboundMessage

logger = logging.getLogger(__name__)


def parse_inbound(event: dict) -> InboundMessage | None:
    """Extract an InboundMessage from a telegramy WS event.

    Args:
        event: A raw telegramy WebSocket event dict.

    Returns:
        An InboundMessage, or None if the event is not a message, has no
        non-empty text, or has no valid numeric sender id.
    """
    msg = event.get("message")
    if not msg:
        return None
    text = (msg.get("text") or "").strip()
    if not text:
        return None
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    raw_id = sender.get("id")
    try:
        sender_user_id = int(raw_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning("dropping message with invalid sender id %r", raw_id)
        return None
    return InboundMessage(
        chat_id=str(chat.get("id")),
        chat_type=str(chat.get("type", "")),
        sender_user_id=sender_user_id,
        sender_username=sender.get("username"),
        sender_first_name=sender.get("first_name"),
        text=text,
    )
