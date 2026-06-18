"""AllowAllList — a test allowlist that admits everyone."""

from relaypi.core.domain.entities.inbound_message import InboundMessage
from relaypi.core.domain.interfaces.allowlist import Allowlist


class AllowAllList(Allowlist):
    def allows(self, msg: InboundMessage) -> bool:
        return True
