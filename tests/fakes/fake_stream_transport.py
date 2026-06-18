"""FakeStreamTransport — a demand-driven fake PI for PIRpcClient tests.

Classical-school fake with REAL behaviour (not a mock): when the client writes a
command, this fake queues the scripted response lines for that command id, which
the client then reads. Responses are demand-driven, so a response is never
consumed before its command is sent (no races in the two-phase prompt ->
get_last_assistant_text flow).

``writes`` records every command the client sent (the observable outcome).
"""

import asyncio
import json


class FakeStreamTransport:
    def __init__(self) -> None:
        self.writes: list[dict] = []
        self._out: asyncio.Queue[bytes] = asyncio.Queue()
        self._script: dict[int, list[dict]] = {}
        self._eof_after: set[int] = set()

    def script_response(self, cmd_id: int, lines: list[dict]) -> None:
        """Queue these JSON lines for read() once command ``cmd_id`` is written."""
        self._script[cmd_id] = list(lines)

    def script_eof_after(self, cmd_id: int) -> None:
        """After command ``cmd_id``'s response lines are queued, deliver EOF (b"").

        Simulates a PI subprocess crash mid-turn: the prompt was accepted and
        its response sent, then stdout closed before the turn finished.
        """
        self._eof_after.add(cmd_id)

    async def write(self, data: bytes) -> None:
        for raw in data.split(b"\n"):
            if not raw.strip():
                continue
            cmd = json.loads(raw.decode("utf-8"))
            self.writes.append(cmd)
            # PI does not answer an extension_ui_response (it's a reply FROM us);
            # only queue scripted lines for commands that expect a response.
            if cmd.get("type") == "extension_ui_response":
                continue
            cid = int(cmd.get("id", -1))
            for line in self._script.get(cid, []):
                await self._out.put((json.dumps(line) + "\n").encode("utf-8"))
            if cid in self._eof_after:
                await self._out.put(b"")  # EOF sentinel -> read() returns b""

    async def read(self, n: int) -> bytes:
        """Return the next scripted line, or b"" once EOF has been signalled."""
        return await self._out.get()

    async def send_unsolicited(self, line: dict) -> None:
        """Push a line the client didn't request (e.g. an extension_ui_request)."""
        await self._out.put((json.dumps(line) + "\n").encode("utf-8"))

    async def close(self) -> None:
        await self._out.put(b"")  # EOF sentinel -> read() returns b""
