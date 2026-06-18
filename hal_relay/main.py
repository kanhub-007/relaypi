"""HAL Relay entry point.

Run with:  python -m hal_relay.main

Windows note: loop.add_signal_handler is unsupported, so shutdown is driven by
KeyboardInterrupt (Ctrl+C / console close). On POSIX you could add SIGTERM/SIGINT
handlers; the try/finally here keeps the same code running on both.
"""

import asyncio
import logging
import sys

from hal_relay.startup.factory import create_relay

logger = logging.getLogger(__name__)


# Connection-classification: match by exception CLASS (isinstance), not by
# type-name string. Name-based matching breaks silently if a library renames an
# exception (websockets has across majors) or if httpx raises a class we didn't
# enumerate. Imports are guarded so the module loads even if a library version
# lacks one of them.
_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    OSError,  # ConnectionRefusedError, ConnectionResetError, etc.
)
try:  # websockets is a hard dep, but guard against rename/removal of exceptions
    from websockets.exceptions import InvalidHandshake as _WS_InvalidHandshake

    _CONNECTION_ERRORS = (*_CONNECTION_ERRORS, _WS_InvalidHandshake)
    try:
        from websockets.exceptions import InvalidStatus as _WS_InvalidStatus

        _CONNECTION_ERRORS = (*_CONNECTION_ERRORS, _WS_InvalidStatus)
    except ImportError:
        pass
    try:
        from websockets.exceptions import InvalidURI as _WS_InvalidURI

        _CONNECTION_ERRORS = (*_CONNECTION_ERRORS, _WS_InvalidURI)
    except ImportError:
        pass
except ImportError:
    pass
try:  # httpx connect errors (telegramy MCP down)
    import httpx as _httpx

    _CONNECTION_ERRORS = (
        *_CONNECTION_ERRORS,
        _httpx.ConnectError,
        _httpx.RemoteProtocolError,
    )
except ImportError:
    pass


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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
