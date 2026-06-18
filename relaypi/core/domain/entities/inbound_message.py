"""InboundMessage transport DTO.

Parsed from a telegramy WebSocket message event. This is data crossing a
boundary, not a rich domain entity — the relay has no business logic to put
in it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    """A parsed inbound Telegram message, ready for allowlist/format/sending.

    Attributes:
        chat_id: Telegram chat id as a string (allowlist + routing key).
        chat_type: "private", "group", "supergroup", etc.
        sender_user_id: Stable numeric user id (the allowlist key).
        sender_username: Unique handle, preferred for the prompt prefix. May be None.
        sender_first_name: Fallback for the prefix when username is absent. May be None.
        text: The message text, stripped of surrounding whitespace.
    """

    chat_id: str
    chat_type: str
    sender_user_id: int
    sender_username: str | None
    sender_first_name: str | None
    text: str
