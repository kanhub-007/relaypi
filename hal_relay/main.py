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


def _is_connection_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a transport-connection failure (e.g. telegramy down).

    We don't want a raw traceback for the very common 'dependencies not running' case;
    a clean log line + non-zero exit is the right UX. Everything else still raises.
    """
    name = type(exc).__name__
    return name in {
        "ConnectionRefusedError",
        "ConnectionResetError",
        "OSError",
        "InvalidStatus",
        "InvalidHandshake",
        "InvalidURI",
    }


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
