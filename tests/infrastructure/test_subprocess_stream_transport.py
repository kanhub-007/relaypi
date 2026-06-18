"""Integration tests for SubprocessStreamTransport — against real subprocesses.

Classical school: these spin up REAL Python subprocesses (the fixtures in
tests/fixtures/), not mocks. They verify the lifecycle that matters operationally:
JSONL round-trips over real pipes, graceful close, and kill-on-hang (no orphans).
"""

import asyncio
import sys
from pathlib import Path

from relaypi.infrastructure.adapters.pi_rpc_client import PIRpcClient
from relaypi.infrastructure.adapters.subprocess_stream_transport import (
    SubprocessStreamTransport,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _echo_argv() -> list[str]:
    return [sys.executable, str(FIXTURES / "echo_pi.py")]


def _hung_argv() -> list[str]:
    return [sys.executable, str(FIXTURES / "hung_pi.py")]


async def _spawn_echo(
    shutdown_timeout: float = 2.0,
) -> tuple[SubprocessStreamTransport, asyncio.subprocess.Process]:
    transport = SubprocessStreamTransport(
        argv=_echo_argv(), shutdown_timeout=shutdown_timeout
    )
    await transport.start()
    assert transport._proc is not None  # type: ignore[attr-defined] - inspect for test
    return transport, transport._proc  # type: ignore[return-value]


async def test_round_trips_jsonl_through_a_real_subprocess():
    transport, proc = await _spawn_echo()
    client = PIRpcClient(transport=transport, turn_timeout=2.0, abort_timeout=1.0)
    try:
        await client.start()
        # echo_pi answers any command with success + same id.
        resp = await client._send_command({"type": "get_last_assistant_text"})
        assert resp["success"] is True
        assert resp["id"] == 1
    finally:
        await client.stop()

    # Process exited cleanly (not orphaned).
    assert proc.returncode == 0


async def test_close_gracefully_terminates_a_well_behaved_process():
    transport, proc = await _spawn_echo(shutdown_timeout=2.0)
    # Write nothing; just close. The process reads EOF and exits 0.
    await transport.close()
    assert proc.returncode == 0


async def test_close_kills_a_process_that_will_not_exit():
    # Hung process ignores stdin close and sleeps forever.
    transport = SubprocessStreamTransport(argv=_hung_argv(), shutdown_timeout=0.5)
    await transport.start()
    proc = transport._proc  # type: ignore[attr-defined]
    assert proc is not None

    # close() must return within a bounded time (not hang) and leave it dead.
    await asyncio.wait_for(transport.close(), timeout=3.0)
    assert proc.returncode is not None  # killed -> has an exit code


def test_subprocess_transport_satisfies_stream_transport_protocol():
    # L1: the Protocol is @runtime_checkable, so the structural-typing claim is
    # actually enforced. SubprocessStreamTransport and FakeStreamTransport both
    # must satisfy it.
    from relaypi.infrastructure.adapters.stream_transport import StreamTransport
    from tests.fakes.fake_stream_transport import FakeStreamTransport

    assert isinstance(SubprocessStreamTransport(argv=_echo_argv()), StreamTransport)
    assert isinstance(FakeStreamTransport(), StreamTransport)
