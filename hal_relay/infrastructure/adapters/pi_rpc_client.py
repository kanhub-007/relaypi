"""PIRpcClient — drives one PI RPC conversation over a StreamTransport.

Implements the AgentClient port. The protocol logic (JSONL framing, command-id
correlation, event demuxing, extension-UI handling) is transport-agnostic and
fully unit-testable with a fake transport; the subprocess wrapper is wired in
startup/ via a real StreamTransport.

Protocol invariants enforced here (see docs/development.md "protocol traps"):
  * LF-only framing on stdout (never split on other line separators).
  * Await the command ``response`` before ``agent_end`` — a rejected prompt
    never emits agent_end, so waiting for it would hang.
  * Always answer ``extension_ui_request`` dialog methods — PI blocks until
    answered; ignoring one deadlocks the turn.
"""

import asyncio
import json
import logging

from hal_relay.core.domain.agent_error import AgentError
from hal_relay.core.domain.interfaces.agent_client import AgentClient
from hal_relay.infrastructure.adapters.stream_transport import StreamTransport

logger = logging.getLogger(__name__)

# Defaults are generous; tests pass shorter values via the constructor.
DEFAULT_TURN_TIMEOUT = 600.0
DEFAULT_ABORT_TIMEOUT = 15.0
# Bound on events queued for an in-flight turn. A chatty PI turn (many
# tool_execution_update deltas from a long bash run) could otherwise grow the
# queue unboundedly. With a maxsize the reader blocks on put -> PI's stdout
# fills -> PI itself blocks, which is the correct backpressure.
MAX_QUEUED_EVENTS = 1000


class PIRpcClient(AgentClient):
    """One PI conversation endpoint over an injected StreamTransport."""

    def __init__(
        self,
        transport: StreamTransport,
        turn_timeout: float = DEFAULT_TURN_TIMEOUT,
        abort_timeout: float = DEFAULT_ABORT_TIMEOUT,
    ) -> None:
        self._transport = transport
        self._turn_timeout = turn_timeout
        self._abort_timeout = abort_timeout
        self._reader_task: asyncio.Task[None] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._event_queue: asyncio.Queue[dict] | None = None  # current turn
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    async def start(self) -> None:
        """Begin the background reader that demuxes PI's stdout."""
        self._alive = True
        self._reader_task = asyncio.create_task(self._read_loop())

    async def prompt_and_collect(self, message: str) -> str:
        """Send a prompt, await turn completion, return final assistant text.

        On turn timeout, aborts the runaway turn (warm process preserved when
        possible) and re-raises so the caller can report an error to the user.
        """
        # Set up the event queue BEFORE sending the command: the reader may emit
        # events (incl. agent_end) the instant the prompt is accepted, and we must
        # not drop them in the gap between "response resolved" and "now listening".
        self._event_queue = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)
        try:
            resp = await self._send_command({"type": "prompt", "message": message})
            if not resp.get("success"):
                raise AgentError(f"PI rejected prompt: {resp.get('error')}")

            while True:
                try:
                    event = await asyncio.wait_for(
                        self._event_queue.get(), timeout=self._turn_timeout
                    )
                except asyncio.TimeoutError:
                    await self.abort()
                    raise AgentError(
                        f"turn timed out after {self._turn_timeout}s and was aborted"
                    )
                if event.get("type") == "agent_end":
                    break
        finally:
            self._event_queue = None

        return await self._get_last_assistant_text()

    async def abort(self) -> None:
        """Cancel the current turn. Escalate to stop() if PI won't ack."""
        try:
            await asyncio.wait_for(
                self._send_command({"type": "abort"}), timeout=self._abort_timeout
            )
        except Exception as exc:
            logger.warning("abort failed/timed out, closing transport: %s", exc)
            await self.stop()

    async def stop(self) -> None:
        """Cancel the reader and close the transport (subprocess killed by it)."""
        if self._reader_task:
            self._reader_task.cancel()
        await self._transport.close()
        self._alive = False

    async def _get_last_assistant_text(self) -> str:
        resp = await self._send_command({"type": "get_last_assistant_text"})
        return (resp.get("data") or {}).get("text") or ""

    async def _send_command(self, cmd: dict) -> dict:
        """Send a command with a fresh id and await its matching response.

        Raises RuntimeError immediately if the stream is already dead — a
        command can never be answered once the reader has stopped, so waiting
        would hang forever. (A command already in flight when the stream dies
        is failed by the reader's finally via _fail_pending.)
        """
        if not self._alive:
            raise AgentError("PI stream closed")
        req_id = self._next_id = self._next_id + 1
        payload = {"id": req_id, **cmd}
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._transport.write((json.dumps(payload) + "\n").encode("utf-8"))
        return await fut

    async def _read_loop(self) -> None:
        """Strict LF framing; demux by message type."""
        buffer = b""
        try:
            while True:
                chunk = await self._transport.read(4096)
                if not chunk:
                    break  # EOF — subprocess exited / transport closed
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.removesuffix(b"\r")
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    await self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("PI reader loop crashed")
        finally:
            self._alive = False
            self._fail_pending(AgentError("PI stream closed"))
            if self._event_queue is not None:
                # Unblock a turn waiting for events so it doesn't hang on timeout.
                self._event_queue.put_nowait({"type": "agent_end"})

    async def _dispatch(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "response":
            fut = self._pending.pop(int(msg.get("id", -1)), None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
        elif t == "extension_ui_request":
            await self._handle_ui_request(msg)  # MUST answer or PI blocks forever
        else:
            if self._event_queue is not None:
                self._event_queue.put_nowait(msg)

    async def _handle_ui_request(self, req: dict) -> None:
        """MVP: auto-respond permissively. Fire-and-forget methods need no reply."""
        method = req.get("method")
        rid = req.get("id")
        if method in ("select", "input", "editor"):
            await self._send_raw(
                {"type": "extension_ui_response", "id": rid, "value": ""}
            )
        elif method == "confirm":
            await self._send_raw(
                {"type": "extension_ui_response", "id": rid, "confirmed": True}
            )
        # notify / setStatus / setWidget / setTitle / set_editor_text: no response.

    async def _send_raw(self, obj: dict) -> None:
        await self._transport.write((json.dumps(obj) + "\n").encode("utf-8"))

    def _fail_pending(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
