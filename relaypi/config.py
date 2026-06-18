"""Config — resolve relay configuration from environment variables.

Config is PURE env-parsing: constructing it does one PATH probe (for the
pi binary via shutil.which) and no other file I/O. The allowlist (which reads
a file) is loaded separately by the composition root via
load_allowlist_from_path, so a unit test of Config never needs to touch the
filesystem, and Config changes for only one reason (a new env var) rather than
two (env var + new allowlist feature).

The ``environ`` parameter supports deterministic testing without monkeypatching.

Environment variables (all optional; listed with defaults):
  RELAYPI_WS_URL    ws://localhost:8765            telegramy WebSocket
  RELAYPI_MCP_URL   http://localhost:8005/mcp      telegramy MCP send endpoint
  RELAYPI_PI_BIN          shutil.which("pi") or "pi"     PI executable (Windows: .cmd shim)
  RELAYPI_PROJECT_DIR     hal                            PI profile directory (AGENTS.md + .pi/)
  RELAYPI_SESSION_DIR     hal/sessions                   per-chat .jsonl root
  RELAYPI_ALLOWLIST       config/allowlist.yaml          allowlist config file path
"""

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

DEFAULT_WS_URL = "ws://localhost:8765"
DEFAULT_MCP_URL = "http://localhost:8005/mcp"
DEFAULT_PROJECT_DIR = "hal"
DEFAULT_SESSION_DIR = "hal/sessions"
# Resolved relative to this file so the default works regardless of cwd
# (the caller can still override via RELAYPI_ALLOWLIST).
_DEFAULT_ALLOWLIST = str(
    Path(__file__).resolve().parent.parent / "config" / "allowlist.yaml"
)


class Config:
    """Relay configuration resolved from an env mapping (default: os.environ)."""

    def __init__(self, environ: Mapping[str, str] = os.environ) -> None:
        self.telegramy_ws_url = environ.get("RELAYPI_WS_URL", DEFAULT_WS_URL)
        self.telegramy_mcp_url = environ.get("RELAYPI_MCP_URL", DEFAULT_MCP_URL)
        # Windows: the global npm install is a `pi.cmd` shim; create_subprocess_exec
        # can't find bare "pi" without shell=True. shutil.which resolves the full
        # path. An explicit RELAYPI_PI_BIN always wins.
        self.pi_bin = environ.get("RELAYPI_PI_BIN") or shutil.which("pi") or "pi"
        self.project_dir = environ.get("RELAYPI_PROJECT_DIR", DEFAULT_PROJECT_DIR)
        self.session_dir = environ.get("RELAYPI_SESSION_DIR", DEFAULT_SESSION_DIR)
        self.allowlist_path = environ.get("RELAYPI_ALLOWLIST", _DEFAULT_ALLOWLIST)
