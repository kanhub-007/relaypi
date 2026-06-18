"""Tests for Config — env-var parsing + allowlist wiring.

``load_allowlist`` (the YAML -> ConfigAllowlist parser) is already covered in
test_allowlist.py; here we cover the Config dataclass that reads env vars and
resolves the PI binary path. File I/O is the only untestable bit (and trivial).
"""

import os

import pytest

from hal_relay.config import Config


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every HAL_* var so tests start from a known empty state."""
    for key in list(os.environ):
        if key.startswith("HAL_"):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_defaults_when_no_env_vars_set(clean_env, monkeypatch):
    import shutil

    cfg = Config()

    assert cfg.telegramy_ws_url == "ws://localhost:8765"
    assert cfg.telegramy_mcp_url == "http://localhost:8005/mcp"
    assert cfg.project_dir == "hal"
    assert cfg.session_dir == "hal/sessions"
    assert cfg.allowlist_path == "config/allowlist.yaml"
    # pi_bin = HAL_PI_BIN or shutil.which("pi") or "pi". We don't assume whether
    # pi happens to be installed on the test host; just assert the contract.
    assert cfg.pi_bin == (shutil.which("pi") or "pi")


def test_env_vars_override_defaults(clean_env, monkeypatch):
    monkeypatch.setenv("HAL_RELAY_WS_URL", "ws://bridge:9000")
    monkeypatch.setenv("HAL_RELAY_MCP_URL", "http://bridge:8005/mcp")
    monkeypatch.setenv("HAL_PI_BIN", "/custom/pi")
    monkeypatch.setenv("HAL_PROJECT_DIR", "/projects/hal")
    monkeypatch.setenv("HAL_SESSION_DIR", "/projects/hal/sess")
    monkeypatch.setenv("HAL_ALLOWLIST", "/etc/allowlist.yaml")

    cfg = Config()

    assert cfg.telegramy_ws_url == "ws://bridge:9000"
    assert cfg.telegramy_mcp_url == "http://bridge:8005/mcp"
    assert cfg.pi_bin == "/custom/pi"
    assert cfg.project_dir == "/projects/hal"
    assert cfg.session_dir == "/projects/hal/sess"
    assert cfg.allowlist_path == "/etc/allowlist.yaml"


def test_explicit_pi_bin_takes_precedence_over_which(clean_env, monkeypatch):
    monkeypatch.setenv("HAL_PI_BIN", "/explicit/path/pi")
    cfg = Config()
    assert cfg.pi_bin == "/explicit/path/pi"


def test_allowlist_loaded_from_config_file(clean_env, monkeypatch, tmp_path):
    from hal_relay.core.application.parse import parse_inbound
    from tests.fakes.event_helpers import msg_event

    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text(
        "dm_users: [123]\n" "groups:\n" "  - id: -100\n" "    mode: open\n"
    )
    monkeypatch.setenv("HAL_ALLOWLIST", str(allowlist))

    cfg = Config()

    # Assert on the allowlist's PUBLIC behaviour, not its decomposed internals.
    assert (
        cfg.allowlist.allows(parse_inbound(msg_event("1", "x", "hi", user_id=123)))
        is True
    )
    assert (
        cfg.allowlist.allows(parse_inbound(msg_event("1", "x", "hi", user_id=999)))
        is False
    )
    assert (
        cfg.allowlist.allows(
            parse_inbound(msg_event("-100", "x", "hi", chat_type="group", user_id=555))
        )
        is True
    )


def test_missing_allowlist_file_fails_closed(clean_env, monkeypatch, tmp_path):
    # An absent allowlist -> empty allowlist -> everything dropped (fail closed).
    monkeypatch.setenv("HAL_ALLOWLIST", str(tmp_path / "does_not_exist.yaml"))
    cfg = Config()

    from hal_relay.core.application.parse import parse_inbound
    from tests.fakes.event_helpers import msg_event

    assert (
        cfg.allowlist.allows(parse_inbound(msg_event("1", "x", "hi", user_id=123)))
        is False
    )
