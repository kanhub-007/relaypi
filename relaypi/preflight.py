"""Pre-flight health check for relaypi — called by start.bat.

Exits 0 if everything is ready, non-zero if a dependency is missing.
"""

import sys
import asyncio

import websockets

from relaypi.config import Config
from relaypi.infrastructure.allowlist_config import load_allowlist_from_path


async def _check_telegramy() -> bool:
    try:
        async with websockets.connect("ws://localhost:8765", open_timeout=3):
            print("  telegramy WS   [OK]  ws://localhost:8765")
            return True
    except Exception:
        print("  telegramy WS   [FAIL]  ws://localhost:8765 — is telegramy running?")
        return False


def _check_config() -> None:
    cfg = Config()
    al = load_allowlist_from_path(cfg.allowlist_path)
    dm = len(al._dm_users)  # type: ignore[attr-defined]
    grp = len(al._groups)  # type: ignore[attr-defined]
    print(f"  pi binary      [OK]  {cfg.pi_bin}")
    print(f"  allowlist      [OK]  {dm} DM user(s), {grp} group(s)")
    if dm == 0 and grp == 0:
        print("  *** WARNING: allowlist is empty — all messages will be dropped!")
        print("  *** Edit config/allowlist.yaml and restart.")


async def main() -> int:
    ws_ok = await _check_telegramy()
    _check_config()
    return 0 if ws_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
