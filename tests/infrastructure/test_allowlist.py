"""Tests for the allowlist trust gate — Scenario 2.

Black-box: build a ConfigAllowlist, feed it InboundMessages, assert on the
boolean outcome. No mocks, no interaction assertions.
"""

import textwrap

import pytest

from relaypi.core.application.parse import parse_inbound
from relaypi.core.domain.entities.group_config import GroupConfig
from relaypi.infrastructure.allowlist_config import (
    ConfigAllowlist,
    load_allowlist,
    load_allowlist_from_path,
)
from tests.fakes.event_helpers import msg_event


def _msg(chat_id, user_id, chat_type="private", username="x"):
    return parse_inbound(
        msg_event(chat_id, username, "hi", chat_type=chat_type, user_id=user_id)
    )


# --- DM gate ---


def test_dm_allowed_only_for_allowlisted_user():
    allowlist = ConfigAllowlist(dm_users={987654321}, groups={})

    # Not allowlisted -> dropped
    assert allowlist.allows(_msg("1", user_id=999)) is False
    # Allowlisted -> allowed
    assert allowlist.allows(_msg("2", user_id=987654321)) is True


# --- Group modes ---


def test_open_group_allows_any_member():
    allowlist = ConfigAllowlist(
        dm_users=set(),
        groups={-100111000: GroupConfig(mode="open")},
    )
    assert allowlist.allows(_msg(-100111000, user_id=555, chat_type="group")) is True


def test_restricted_group_allows_only_listed_members():
    allowlist = ConfigAllowlist(
        dm_users=set(),
        groups={
            -100222000: GroupConfig(mode="restricted", members=frozenset({111222333}))
        },
    )
    # Member -> allowed
    assert (
        allowlist.allows(_msg(-100222000, user_id=111222333, chat_type="group")) is True
    )
    # Non-member -> dropped
    assert allowlist.allows(_msg(-100222000, user_id=999, chat_type="group")) is False


# --- Config validation (M2): invalid modes surface at load time ---


def test_load_allowlist_rejects_unknown_mode():
    for bad in ("opne", "OPEN", "public", "", "allow"):
        with pytest.raises(ValueError, match="invalid group mode"):
            load_allowlist(f"groups:\n  - id: -1\n    mode: {bad}\n"), bad


def test_load_allowlist_accepts_open_and_restricted():
    allowlist = load_allowlist(
        "groups:\n"
        "  - id: -1\n    mode: open\n"
        "  - id: -2\n    mode: restricted\n    members: [1]\n"
    )
    assert allowlist.allows(_msg(-1, user_id=555, chat_type="group")) is True
    assert allowlist.allows(_msg(-2, user_id=1, chat_type="group")) is True


# --- Edge cases (the scenario's "also test" list) ---


def test_unconfigured_group_chat_dropped():
    allowlist = ConfigAllowlist(dm_users={987654321}, groups={})
    assert (
        allowlist.allows(_msg(-999999, user_id=987654321, chat_type="group")) is False
    )


def test_unconfigured_chat_type_dropped():
    allowlist = ConfigAllowlist(dm_users={987654321}, groups={})
    # "channel" is neither private nor a configured group
    assert (
        allowlist.allows(_msg(-100333000, user_id=987654321, chat_type="channel"))
        is False
    )


# --- Config loading from YAML ---


def test_allowlist_loaded_from_yaml_config():
    yaml_text = textwrap.dedent("""
        dm_users: [987654321]
        groups:
          - id: -100111000
            mode: open
          - id: -100222000
            mode: restricted
            members: [987654321, 111222333]
        """)
    allowlist = load_allowlist(yaml_text)

    # DM user allowed
    assert allowlist.allows(_msg("1", user_id=987654321)) is True
    # Open group: any member
    assert allowlist.allows(_msg(-100111000, user_id=555, chat_type="group")) is True
    # Restricted group: member allowed, stranger dropped
    assert (
        allowlist.allows(_msg(-100222000, user_id=111222333, chat_type="group")) is True
    )
    assert allowlist.allows(_msg(-100222000, user_id=999, chat_type="group")) is False


# --- load_allowlist_from_path (M1): file I/O + fail-closed ---


def test_load_allowlist_from_path_reads_yaml_file(tmp_path):
    from tests.fakes.event_helpers import msg_event

    from relaypi.core.application.parse import parse_inbound

    f = tmp_path / "allowlist.yaml"
    f.write_text("dm_users: [123]\n" "groups:\n  - id: -100\n    mode: open\n")
    allowlist = load_allowlist_from_path(str(f))
    assert (
        allowlist.allows(parse_inbound(msg_event("1", "x", "hi", user_id=123))) is True
    )
    assert (
        allowlist.allows(parse_inbound(msg_event("1", "x", "hi", user_id=999))) is False
    )


def test_load_allowlist_from_path_fails_closed_when_missing(tmp_path):
    # Missing file -> empty allowlist (everything dropped), no raise.
    from tests.fakes.event_helpers import msg_event

    from relaypi.core.application.parse import parse_inbound

    allowlist = load_allowlist_from_path(str(tmp_path / "absent.yaml"))
    assert (
        allowlist.allows(parse_inbound(msg_event("1", "x", "hi", user_id=123))) is False
    )


def test_load_allowlist_from_path_fails_closed_when_unreadable(tmp_path):
    # A directory (or any OSError) -> empty allowlist, no raise.
    from tests.fakes.event_helpers import msg_event

    from relaypi.core.application.parse import parse_inbound

    allowlist = load_allowlist_from_path(str(tmp_path))  # tmp_path is a directory
    assert (
        allowlist.allows(parse_inbound(msg_event("1", "x", "hi", user_id=123))) is False
    )
