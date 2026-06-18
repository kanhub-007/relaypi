"""Minimal "PI" responder for SubprocessStreamTransport integration tests.

Reads JSON commands (one per line) from stdin and echoes a success response
with the same id. This lets us exercise the real subprocess lifecycle
(spawn / framing / close / kill) without depending on the real PI binary.

Not a mock of the system under test — a real, standalone process behaving
like a minimal RPC peer.
"""

import json
import sys


def main() -> None:
    # Line-buffered stdin so the parent gets responses promptly.
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = {
            "type": "response",
            "id": cmd.get("id"),
            "command": cmd.get("type"),
            "success": True,
        }
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
