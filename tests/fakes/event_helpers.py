"""Event helpers — build telegramy-shaped message events for tests.

Matches the actual telegramy WebSocket event format (verified against a live
telegramy instance)::

    {"type": "message", "event": {"chat_id": "566302374",
     "from_user": {"id": 566302374, "first_name": "...", "username": "..."},
     "text": "hi"}}

chat_type is NOT a field in the real event — it is inferred by parse_inbound
from the chat_id (private when chat_id matches sender id, group when negative).
"""

from __future__ import annotations


def msg_event(
    chat_id: str,
    username: str | None,
    text: str,
    user_id: int = 1,
    first_name: str = "X",
) -> dict:
    """Build a telegramy WebSocket message event for tests.

    Args:
        chat_id: Chat id (string form). For DMs this should equal str(user_id).
        username: Sender username (may be None for first_name fallback tests).
        text: Message text.
        user_id: Numeric sender id.
        first_name: Sender first name (used for fallback-prefix tests).

    Returns:
        A dict shaped like the real telegramy WS event.
    """
    sender: dict = {"id": user_id, "first_name": first_name}
    if username is not None:
        sender["username"] = username
    return {
        "type": "message",
        "event": {
            "chat_id": chat_id,
            "from_user": sender,
            "text": text,
        },
    }
