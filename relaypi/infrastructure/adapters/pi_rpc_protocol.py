"""PiRpcProtocol — PI JSONL RPC framing, correlation, and event demuxing.

Extracted from PIRpcClient to separate protocol mechanics (byte framing,
request-response correlation, event queue management, UI request handling)
from turn lifecycle concerns (timeout, abort escalation, prompt_orchestration).

The protocol is transport-agnostic: it speaks JSONL over the injected
StreamTransport seam and is fully unit-testable with FakeStreamTransport.
"""

import asyncio
import json
import logging

from relaypi.core.domain.agent_error import AgentError
from relaypi.infrastructure.adapters.stream_transport import StreamTransport

logger = logging.getLogger(__name__)

# Bound on events queued for an in-flight turn. A chatty PI turn (many
# tool_execution_update deltas from a long bash run) could otherwise grow the
# queue unboundedly. With a maxsize the reader blocks on put -> PI's stdout
# fills -> PI itself blocks, which is the correct backpressure.
MAX_QUEUED_EVENTS = 1000


class PiRpcProtocol:
    """PI JSONL RPC protocol handler: framing, correlation, event demuxing.

    Responsibilities:
      * LF-delimited JSONL framing (read/write over StreamTransport)
      * Command id → response correlation
      * Event queue per turn (begin_turn / wait_for_event / end_turn)
      * Extension UI request auto-response (never deadlock PI)
      * Liveness tracking

    NOT responsible for:
      * Turn timeouts (caller wraps wait_for_event)
      * Abort → kill escalation (caller decides policy)
      * Orchestrating prompt → collect flow (caller sequences commands)
    """

    def __init__(self, transport: StreamTransport) -> None:
        self._transport = transport
        self._reader_task: asyncio.Task[None] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._event_queue: asyncio.Queue[dict] | None = None
        self._alive = False

    # -- public API -----------------------------------------------------------

    @property
    def alive(self) -> bool:
        """True while the background reader is running."""
        return self._alive

    async def start(self) -> None:
        """Begin the background reader that demuxes PI's stdout."""
        self._alive = True
        self._reader_task = asyncio.create_task(self._read_loop())

    async def send_command(self, cmd: dict) -> dict:
        """Send a command with a fresh id and await its matching response.

        Raises AgentError immediately if the stream is already dead — a
        command can never be answered once the reader has stopped, so waiting
        would hang forever.
        """
        if not self._alive:
            raise AgentError("PI stream closed")
        req_id = self._next_id = self._next_id + 1
        payload = {"id": req_id, **cmd}
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._send_raw(payload)
        return await fut

    def begin_turn(self) -> None:
        """Create the event queue for a new prompt turn.

        Must be called BEFORE send_command("prompt") so that events arriving
        between the response acknowledgment and the event-consumption loop
        are not dropped.
        """
        self._event_queue = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)

    def end_turn(self) -> None:
        """Clear the event queue (turn finished or aborted)."""
        self._event_queue = None

    async def wait_for_event(self, timeout: float | None = None) -> dict:
        """Return the next event from the turn's event queue.

        Args:
            timeout: Seconds to wait, or None to wait indefinitely.

        Returns:
            The next event dict from PI's stdout.

        Raises:
            asyncio.TimeoutError: If no event arrives within ``timeout``.
        """
        if self._event_queue is None:
            # Synthesize an agent_end so the caller's loop exits cleanly
            # rather than hanging on a turn whose queue was torn down.
            return {"type": "agent_end"}
        if timeout is not None:
            return await asyncio.wait_for(self._event_queue.get(), timeout=timeout)
        return await self._event_queue.get()

    async def stop(self) -> None:
        """Cancel the reader and close the transport."""
        if self._reader_task:
            self._reader_task.cancel()
        await self._transport.close()
        self._alive = False

    # -- internal -------------------------------------------------------------

    async def _send_raw(self, obj: dict) -> None:
        """Fire-and-forget write (no id tracking)."""
        await self._transport.write((json.dumps(obj) + "\n").encode("utf-8"))

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

    def _fail_pending(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
