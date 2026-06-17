"""FakeMessageSource — yields a fixed list of events, then stops.

Classical-school test double: real behaviour (an in-memory async generator),
no recording of interactions.
"""

from collections.abc import AsyncIterator


class FakeMessageSource:
    def __init__(self, events: list[dict]) -> None:
        self._events = list(events)

    async def events(self) -> AsyncIterator[dict]:
        for event in self._events:
            yield event
