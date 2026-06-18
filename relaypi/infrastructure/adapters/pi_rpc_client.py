"""PIRpcClient — drives one PI RPC conversation over a StreamTransport.

Implements the AgentClient port. Turn lifecycle and timeout/abort policy live
here; protocol mechanics (framing, correlation, event demuxing, UI request
handling) are delegated to PiRpcProtocol so each is testable independently.

Protocol invariants enforced here (see docs/development.md "protocol traps"):
  * Event queue set up BEFORE the prompt command is sent (PiRpcProtocol.begin_turn).
  * Turn timeout → abort (warm process preserved when possible), then escalate
    to stop() if PI cannot ack the abort.
"""

import asyncio
import logging

from relaypi.core.domain.agent_error import AgentError
from relaypi.core.domain.interfaces.agent_client import AgentClient
from relaypi.infrastructure.adapters.pi_rpc_protocol import PiRpcProtocol
from relaypi.infrastructure.adapters.stream_transport import StreamTransport

logger = logging.getLogger(__name__)

# Defaults are generous; tests pass shorter values via the constructor.
DEFAULT_TURN_TIMEOUT = 600.0
DEFAULT_ABORT_TIMEOUT = 15.0


class PIRpcClient(AgentClient):
    """One PI conversation endpoint over an injected StreamTransport.

    Turn orchestration (timeout, abort escalation) lives here.
    Protocol mechanics (framing, correlation, demuxing) live in PiRpcProtocol.
    """

    def __init__(
        self,
        transport: StreamTransport,
        turn_timeout: float = DEFAULT_TURN_TIMEOUT,
        abort_timeout: float = DEFAULT_ABORT_TIMEOUT,
    ) -> None:
        self._proto = PiRpcProtocol(transport)
        self._turn_timeout = turn_timeout
        self._abort_timeout = abort_timeout

    def is_alive(self) -> bool:
        return self._proto.alive

    async def start(self) -> None:
        """Begin the background reader that demuxes PI's stdout."""
        await self._proto.start()

    async def prompt_and_collect(self, message: str) -> str:
        """Send a prompt, await turn completion, return final assistant text.

        On turn timeout, aborts the runaway turn (warm process preserved when
        possible) and re-raises so the caller can report an error to the user.
        """
        # Set up the event queue BEFORE sending the command: the reader may emit
        # events (incl. agent_end) the instant the prompt is accepted, and we must
        # not drop them in the gap between "response resolved" and "now listening".
        self._proto.begin_turn()
        try:
            resp = await self._proto.send_command(
                {"type": "prompt", "message": message}
            )
            if not resp.get("success"):
                raise AgentError(f"PI rejected prompt: {resp.get('error')}")

            while True:
                try:
                    event = await self._proto.wait_for_event(timeout=self._turn_timeout)
                except asyncio.TimeoutError:
                    await self.abort()
                    raise AgentError(
                        f"turn timed out after {self._turn_timeout}s and was aborted"
                    )
                if event.get("type") == "agent_end":
                    break
        finally:
            self._proto.end_turn()

        return await self._get_last_assistant_text()

    async def abort(self) -> None:
        """Cancel the current turn. Escalate to stop() if PI won't ack."""
        try:
            await asyncio.wait_for(
                self._proto.send_command({"type": "abort"}),
                timeout=self._abort_timeout,
            )
        except Exception as exc:
            logger.warning("abort failed/timed out, closing transport: %s", exc)
            await self.stop()

    async def stop(self) -> None:
        """Cancel the reader and close the transport (subprocess killed by it)."""
        await self._proto.stop()

    async def _get_last_assistant_text(self) -> str:
        resp = await self._proto.send_command({"type": "get_last_assistant_text"})
        return (resp.get("data") or {}).get("text") or ""
