"""format_prompt — wrap an InboundMessage into the PI prompt prefix.

Pure function: chooses a display name (username > first_name > anonymous)
and prefixes it alongside the chat_id so PI can call telegramy media tools
(send_audio, send_photo, send_file) directly.
"""

from relaypi.core.domain.entities.formatted_prompt import FormattedPrompt
from relaypi.core.domain.entities.inbound_message import InboundMessage


def format_prompt(msg: InboundMessage) -> FormattedPrompt:
    """Format an InboundMessage into a prompt for PI.

    Args:
        msg: The parsed inbound message.

    Returns:
        A FormattedPrompt whose text is
        ``[from={name}][chat={chat_id}] {message}``, where name is the
        sender's username, or first_name, or "anonymous".
    """
    name = msg.sender_username or msg.sender_first_name or "anonymous"
    return FormattedPrompt(
        text=f"[from={name}][chat={msg.chat_id}] {msg.text}"
    )
