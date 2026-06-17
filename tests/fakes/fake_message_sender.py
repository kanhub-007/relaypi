"""FakeMessageSender — records sent messages.

Classical-school test double: records outcomes in ``sent`` rather than
verifying interactions.
"""


class FakeMessageSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, chat_id: str, text: str) -> None:
        self.sent.append({"chat_id": chat_id, "text": text})

    async def close(self) -> None:
        pass
