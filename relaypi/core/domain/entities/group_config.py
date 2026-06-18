"""GroupConfig transport DTO — one allowlist group entry."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GroupConfig:
    """Configuration for a whitelisted group chat.

    Attributes:
        mode: "open" (any member may use the agent) or "restricted" (only listed
            ``members`` may use the agent).
        members: User ids allowed when mode is "restricted". Empty for open.
    """

    mode: str
    members: frozenset[int] = field(default_factory=frozenset)
