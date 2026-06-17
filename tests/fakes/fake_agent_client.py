"""FakeAgentClient — records outgoing commands, returns a canned reply.

Classical-school test double. Records prompts/aborts in ``commands`` so tests
can assert on what was sent (outcome of the routing decision), without
interaction assertions on a mock.
"""


class FakeAgentClient:
    def __init__(self, reply: str = "[ok]", alive: bool = True) -> None:
        self.commands: list[dict] = []  # outgoing: prompt / abort / ui_response
        self._reply = reply
        self._alive = alive

    async def prompt_and_collect(self, message: str) -> str:
        self.commands.append({"type": "prompt", "message": message})
        return self._reply

    async def abort(self) -> None:
        self.commands.append({"type": "abort"})

    def is_alive(self) -> bool:
        return self._alive

    async def stop(self) -> None:
        self._alive = False
