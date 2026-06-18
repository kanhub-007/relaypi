"""Presenter — user-facing reply text authored by the relay.

The Relay is an orchestrator (trust -> route -> format -> prompt -> capture ->
send); authoring user-facing copy is a Presenter concern (AGENTS.md Q6
Facade/Presenter). Keeping the strings here means the orchestrator doesn't
accrete presentation logic as more message kinds are added (error replies,
busy notices, too-long notices, ...).
"""


class Presenter:
    """User-facing reply text for the relay's outbound messages."""

    # Sent to the user when a turn fails operationally (PI down, rejected,
    # timed out) or when an unexpected error occurs while handling their message.
    ERROR_REPLY_TEXT = "⚠️ Something went wrong processing that. Try again."
