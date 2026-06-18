"""Allowlist port — trust gate. Pure: no I/O."""

from abc import ABC, abstractmethod

from relaypi.core.domain.entities.inbound_message import InboundMessage


class Allowlist(ABC):
    """Decides whether an inbound message is allowed to reach HAL."""

    @abstractmethod
    def allows(self, msg: InboundMessage) -> bool:
        """True if the sender/chat combination is trusted."""
        ...
