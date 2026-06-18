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


async def main() -> None:
    relay = create_relay()
    try:
        await relay.run()
    except KeyboardInterrupt:
        pass
    finally:
        await relay.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
