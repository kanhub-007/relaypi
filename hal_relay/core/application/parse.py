"""parse_inbound — extract an InboundMessage from a telegramy WS event.

Pure function: no I/O, no globals. Returns None for non-message events or
empty text so the caller can skip them.
"""

from hal_relay.core.domain.entities.inbound_message import InboundMessage


def parse_inbound(event: dict) -> InboundMessage | None:
    """Extract an InboundMessage from a telegramy WS event.

    Args:
        event: A raw telegramy WebSocket event dict.

    Returns:
        An InboundMessage, or None if the event is not a message or has no
        non-empty text.
    """
    msg = event.get("message")
    if not msg:
        return None
    text = (msg.get("text") or "").strip()
    if not text:
        return None
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    return InboundMessage(
        chat_id=str(chat.get("id")),
        chat_type=str(chat.get("type", "")),
        sender_user_id=int(sender.get("id", 0)),
        sender_username=sender.get("username"),
        sender_first_name=sender.get("first_name"),
        text=text,
    )
