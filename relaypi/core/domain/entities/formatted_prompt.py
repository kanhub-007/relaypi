"""FormattedPrompt transport DTO.

The string the relay sends to PI via RPC ``prompt``. Includes chat_id so
PI can reply directly via its telegramy extension for media sends (audio,
files, photos) — the relay only handles text replies.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FormattedPrompt:
    """A message ready for PI's stdin.

    Format: ``[from={username}][chat={chat_id}] {message}``.
    chat_id is included so PI's telegramy extension can target the
    correct chat for media sends (send_audio, send_photo, send_file).
    """

    text: str
