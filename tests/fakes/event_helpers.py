"""Event helpers — build telegramy-shaped message events for tests."""

from __future__ import annotations


def msg_event(
    chat_id: str,
    username: str,
    text: str,
    chat_type: str = "private",
    user_id: int = 1,
    first_name: str = "X",
) -> dict:
    """Build a telegramy WebSocket message event for tests.

    Args:
        chat_id: Chat id (string form).
        username: Sender username.
        text: Message text.
        chat_type: "private" (default), "group", or "supergroup".
        user_id: Numeric sender id.
        first_name: Sender first name (used for fallback-prefix tests).

    Returns:
        A dict shaped like ``{"message": {...}}``.
    """
    return {
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": user_id, "username": username, "first_name": first_name},
            "text": text,
        }
    }
