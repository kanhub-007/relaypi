"""FormattedPrompt transport DTO.

The display-only string the relay sends to PI via RPC ``prompt``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FormattedPrompt:
    """A message ready for PI's stdin, prefixed with the sender's display name.

    The prefix is display-only: ``[from={username}] {message}``. chat_id is
    deliberately NOT included — the relay holds it for routing/sending.
    """

    text: str
