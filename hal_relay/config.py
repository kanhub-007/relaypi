"""Config — load relay configuration from env vars + allowlist.yaml.

Environment variables (all optional; listed with defaults):
  HAL_RELAY_WS_URL    ws://localhost:8765            telegramy WebSocket
  HAL_RELAY_MCP_URL   http://localhost:8005/mcp      telegramy MCP send endpoint
  HAL_PI_BIN          shutil.which("pi") or "pi"     PI executable (Windows: .cmd shim)
  HAL_PROJECT_DIR     hal                            HAL project dir (AGENTS.md + .pi/)
  HAL_SESSION_DIR     hal/sessions                   per-chat .jsonl root
  HAL_ALLOWLIST       config/allowlist.yaml          allowlist config file

The allowlist is read from disk here (the only I/O in this module) and parsed
via load_allowlist, which is independently unit-tested.
"""

import os
import shutil

from hal_relay.infrastructure.allowlist_config import ConfigAllowlist, load_allowlist

DEFAULT_WS_URL = "ws://localhost:8765"
DEFAULT_MCP_URL = "http://localhost:8005/mcp"
DEFAULT_PROJECT_DIR = "hal"
DEFAULT_SESSION_DIR = "hal/sessions"
DEFAULT_ALLOWLIST = "config/allowlist.yaml"


class Config:
    """Relay configuration resolved from the environment + allowlist file."""

    def __init__(self) -> None:
        self.telegramy_ws_url = os.environ.get("HAL_RELAY_WS_URL", DEFAULT_WS_URL)
        self.telegramy_mcp_url = os.environ.get("HAL_RELAY_MCP_URL", DEFAULT_MCP_URL)
        # Windows: the global npm install is a `pi.cmd` shim; create_subprocess_exec
        # can't find bare "pi" without shell=True. shutil.which resolves the full
        # path. An explicit HAL_PI_BIN always wins.
        self.pi_bin = os.environ.get("HAL_PI_BIN") or shutil.which("pi") or "pi"
        self.project_dir = os.environ.get("HAL_PROJECT_DIR", DEFAULT_PROJECT_DIR)
        self.session_dir = os.environ.get("HAL_SESSION_DIR", DEFAULT_SESSION_DIR)
        self.allowlist_path = os.environ.get("HAL_ALLOWLIST", DEFAULT_ALLOWLIST)
        self.allowlist: ConfigAllowlist = self._load_allowlist()

    def _load_allowlist(self) -> ConfigAllowlist:
        try:
            with open(self.allowlist_path, encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            # No allowlist file -> empty allowlist (drops everything). Fail closed.
            text = ""
        return load_allowlist(text)
