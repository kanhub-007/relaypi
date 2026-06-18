"""RelayPI entry point.

Run with:  python -m relaypi.main

This module lives at the package root (not presentation/) by design — the
implementation guide (specs/.../04-implementation.md Step 8) puts it here as
the thinnest possible entry point. It has startup/-layer import permissions:
it can import from infrastructure for connection-error classification and
call the composition root.

Windows note: loop.add_signal_handler is unsupported, so shutdown is driven by
KeyboardInterrupt (Ctrl+C / console close). On POSIX you could add SIGTERM/SIGINT
handlers; the try/finally here keeps the same code running on both.
"""

import asyncio
import logging
import os
import sys

import httpx
import websockets.exceptions

from relaypi.startup.factory import create_relay

logger = logging.getLogger(__name__)

# Connection-classification: match by exception CLASS (isinstance), not by
# type-name string. Name-based matching breaks silently if a library renames an
# exception (websockets has across majors) or if httpx raises a class we didn't
# enumerate.
_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    OSError,  # ConnectionRefusedError, ConnectionResetError, etc.
    websockets.exceptions.InvalidHandshake,
    websockets.exceptions.InvalidStatus,
    websockets.exceptions.InvalidURI,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)


def _is_connection_error(exc: BaseException) -> bool:
    """True if ``exc`` is a transport-connection failure (e.g. telegramy down).

    We don't want a raw traceback for the very common 'dependencies not running'
    case; a clean log line + non-zero exit is the right UX. Everything else
    still raises.
    """
    return isinstance(exc, _CONNECTION_ERRORS)


async def main() -> int:
    relay = create_relay()
    try:
        await relay.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        if _is_connection_error(exc):
            logger.error(
                "cannot reach a dependency (telegramy WebSocket or PI): %s. "
                "Are the services running?",
                exc,
            )
            return 1
        raise  # genuine bug -> let it surface as a traceback
    finally:
        await relay.stop()
    return 0


if __name__ == "__main__":
    log_level = os.environ.get("RELAYPI_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
