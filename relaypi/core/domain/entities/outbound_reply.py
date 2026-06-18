"""OutboundReply transport DTO.

Data crossing from the application layer to the MessageSender infrastructure
boundary. Carries the chat_id (routing key) and the user-facing text.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OutboundReply:
    """A reply ready to be sent to a Telegram chat.

    Attributes:
        chat_id: Telegram chat id as a string (routing key for the sender).
        text: The user-facing message text.
    """

    chat_id: str
    text: str
