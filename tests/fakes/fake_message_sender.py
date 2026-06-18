"""FakeMessageSender — records sent messages.

Classical-school test double: records outcomes in ``sent`` rather than
verifying interactions.
"""

from relaypi.core.domain.entities.outbound_reply import OutboundReply
from relaypi.core.domain.interfaces.message_sender import MessageSender


class FakeMessageSender(MessageSender):
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, reply: OutboundReply) -> None:
        self.sent.append({"chat_id": reply.chat_id, "text": reply.text})

    async def close(self) -> None:
        pass
