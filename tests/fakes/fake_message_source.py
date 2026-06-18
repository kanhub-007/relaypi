"""FakeMessageSource — yields a fixed list of events, then stops.

Classical-school test double: real behaviour (an in-memory async generator),
no recording of interactions.
"""

from collections.abc import AsyncGenerator

from relaypi.core.domain.interfaces.message_source import MessageSource


class FakeMessageSource(MessageSource):
    def __init__(self, events: list[dict]) -> None:
        self._events = list(events)

    async def events(self) -> AsyncGenerator[dict, None]:
        for event in self._events:
            yield event
