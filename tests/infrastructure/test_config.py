"""Tests for Config — pure env-var parsing (no file I/O).

``load_allowlist`` (YAML text) and ``load_allowlist_from_path`` (file) are
covered in test_allowlist.py. Config itself must not touch the filesystem.
"""

import os
import shutil

import pytest

from relaypi.config import Config


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every HAL_* var so tests start from a known empty state."""
    for key in list(os.environ):
        if key.startswith("HAL_"):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_defaults_when_no_env_vars_set(clean_env):
    cfg = Config()

    assert cfg.telegramy_ws_url == "ws://localhost:8765"
    assert cfg.telegramy_mcp_url == "http://localhost:8005/mcp"
    assert cfg.project_dir == "hal"
    assert cfg.session_dir == "hal/sessions"
    assert cfg.allowlist_path == "config/allowlist.yaml"
    # pi_bin = RELAYPI_PI_BIN or shutil.which("pi") or "pi". We don't assume whether
    # pi happens to be installed on the test host; just assert the contract.
    assert cfg.pi_bin == (shutil.which("pi") or "pi")


def test_env_vars_override_defaults(clean_env, monkeypatch):
    monkeypatch.setenv("RELAYPI_WS_URL", "ws://bridge:9000")
    monkeypatch.setenv("RELAYPI_MCP_URL", "http://bridge:8005/mcp")
    monkeypatch.setenv("RELAYPI_PI_BIN", "/custom/pi")
    monkeypatch.setenv("RELAYPI_PROJECT_DIR", "/projects/hal")
    monkeypatch.setenv("RELAYPI_SESSION_DIR", "/projects/hal/sess")
    monkeypatch.setenv("RELAYPI_ALLOWLIST", "/etc/allowlist.yaml")

    cfg = Config()

    assert cfg.telegramy_ws_url == "ws://bridge:9000"
    assert cfg.telegramy_mcp_url == "http://bridge:8005/mcp"
    assert cfg.pi_bin == "/custom/pi"
    assert cfg.project_dir == "/projects/hal"
    assert cfg.session_dir == "/projects/hal/sess"
    assert cfg.allowlist_path == "/etc/allowlist.yaml"


def test_explicit_pi_bin_takes_precedence_over_which(clean_env, monkeypatch):
    monkeypatch.setenv("RELAYPI_PI_BIN", "/explicit/path/pi")
    cfg = Config()
    assert cfg.pi_bin == "/explicit/path/pi"


def test_config_does_not_read_the_allowlist_file(clean_env, monkeypatch, tmp_path):
    # M1: constructing Config must not do file I/O. Pointing allowlist_path at a
    # nonexistent file must NOT raise (and must NOT load anything) — the factory
    # loads the allowlist later, separately.
    missing = tmp_path / "does_not_exist.yaml"
    monkeypatch.setenv("RELAYPI_ALLOWLIST", str(missing))

    cfg = Config()  # no raise

    assert cfg.allowlist_path == str(missing)
    assert not hasattr(cfg, "allowlist")  # Config no longer holds an allowlist
