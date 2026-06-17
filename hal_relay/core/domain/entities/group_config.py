"""GroupConfig transport DTO — one allowlist group entry."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GroupConfig:
    """Configuration for a whitelisted group chat.

    Attributes:
        mode: "open" (any member may use HAL) or "restricted" (only listed
            ``members`` may use HAL).
        members: User ids allowed when mode is "restricted". Empty for open.
    """

    mode: str
    members: frozenset[int] = field(default_factory=frozenset)
