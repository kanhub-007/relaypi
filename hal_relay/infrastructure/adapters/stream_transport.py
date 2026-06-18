"""StreamTransport — the I/O seam for PIRpcClient.

PIRpcClient speaks PI's JSONL RPC protocol but is agnostic to HOW bytes reach
it: a subprocess's stdin/stdout, or an in-memory fake for tests. This Protocol
defines that seam. The real subprocess-backed implementation lives alongside
the client factory in startup/; tests use FakeStreamTransport.

Framing contract (per PI docs/rpc.md):
  * write(): send raw bytes (JSON commands, one per line, LF-terminated).
  * read(n): return up to n bytes; return b"" to signal EOF (peer closed).
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StreamTransport(Protocol):
    """A bidirectional byte stream with LF-delimited framing."""

    async def write(self, data: bytes) -> None:
        """Send bytes to the peer (PI's stdin)."""
        ...

    async def read(self, n: int) -> bytes:
        """Read up to n bytes; return b"" at EOF."""
        ...

    async def close(self) -> None:
        """Close the stream and signal EOF to a pending read."""
        ...
