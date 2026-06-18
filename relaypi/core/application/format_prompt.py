"""format_prompt — wrap an InboundMessage into the PI prompt prefix.

Pure function: chooses a display name (username > first_name > anonymous)
and prepends it. chat_id never appears here — that's a load-bearing invariant
(see 03-domain.md and test_chat_id_never_enters_formatted_prompt).
"""

from relaypi.core.domain.entities.formatted_prompt import FormattedPrompt
from relaypi.core.domain.entities.inbound_message import InboundMessage


def format_prompt(msg: InboundMessage) -> FormattedPrompt:
    """Format an InboundMessage into a display-only prompt for PI.

    Args:
        msg: The parsed inbound message.

    Returns:
        A FormattedPrompt whose text is ``[from={name}] {message}``, where
        name is the sender's username, or first_name, or "anonymous".
    """
    name = msg.sender_username or msg.sender_first_name or "anonymous"
    return FormattedPrompt(text=f"[from={name}] {msg.text}")
