"""BlockingAgentClient — a fake whose prompt_and_collect blocks until released.

For concurrency tests (Scenario 4). Each call creates a Future stored in
``pending``; the test resolves a future to release that call. The number of
entries in ``pending`` is the observable "how many prompts are in flight".
"""

import asyncio


class BlockingAgentClient:
    def __init__(self) -> None:
        self.commands: list[dict] = []
        self.pending: list[asyncio.Future[None]] = []

    async def prompt_and_collect(self, message: str) -> str:
        self.commands.append({"type": "prompt", "message": message})
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.pending.append(fut)
        await fut  # blocks until the test resolves this future
        return "[ok]"

    async def abort(self) -> None:
        pass

    def is_alive(self) -> bool:
        return True

    async def stop(self) -> None:
        pass
