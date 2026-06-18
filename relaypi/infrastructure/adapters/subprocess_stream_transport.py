"""SubprocessStreamTransport — wraps a PI subprocess behind the StreamTransport seam.

This is the production transport for PIRpcClient. It spawns the PI RPC process
and exposes stdin/stdout as the write/read/close surface the client expects.

Lifecycle:
  * start(): spawn the process with stdin/stdout pipes.
  * write()/read(): pipe I/O (LF-delimited JSONL; framing is the client's job).
  * close(): close stdin (graceful EOF), wait bounded by ``shutdown_timeout``,
    then kill() if it won't exit. Guarantees no orphaned subprocess and never
    hangs the relay's shutdown.

``start()`` is intentionally NOT part of the StreamTransport Protocol — only
this concrete implementation needs it; the composition root calls it before
handing the transport to PIRpcClient.
"""

import asyncio
import logging
from asyncio import subprocess

from relaypi.infrastructure.adapters.stream_transport import StreamTransport

logger = logging.getLogger(__name__)


class SubprocessStreamTransport(StreamTransport):
    """A StreamTransport backed by a child process's stdin/stdout pipes."""

    def __init__(
        self,
        argv: list[str],
        cwd: str | None = None,
        shutdown_timeout: float = 5.0,
    ) -> None:
        self._argv = list(argv)
        self._cwd = cwd
        self._shutdown_timeout = shutdown_timeout
        self._proc: subprocess.Process | None = None

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode if self._proc is not None else None

    async def start(self) -> None:
        """Spawn the process with piped stdin/stdout."""
        logger.info("starting subprocess: %s (cwd=%s)", " ".join(self._argv), self._cwd)
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            cwd=self._cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Let stderr inherit so PI's own logs surface during development.
            stderr=None,
        )

    async def write(self, data: bytes) -> None:
        """Write bytes to the process's stdin."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("SubprocessStreamTransport not started")
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

    async def read(self, n: int) -> bytes:
        """Read up to n bytes from stdout; b"" at EOF (process exited/closed)."""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("SubprocessStreamTransport not started")
        return await self._proc.stdout.read(n)

    async def close(self) -> None:
        """Close stdin, wait bounded, then kill. Never hangs; never orphans."""
        if self._proc is None:
            return
        proc = self._proc
        if proc.stdin is not None:
            proc.stdin.close()  # signal graceful exit
        try:
            await asyncio.wait_for(proc.wait(), timeout=self._shutdown_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "subprocess did not exit within %.1fs; killing", self._shutdown_timeout
            )
            proc.kill()
            await proc.wait()  # reap the killed process
