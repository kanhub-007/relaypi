"""ConfigAllowlist — static allowlist loaded from YAML config.

Implements the Allowlist port. Pure decision logic (no I/O in ``allows``);
loading from YAML text lives in ``load_allowlist`` below, and loading from a
file path lives in ``load_allowlist_from_path`` (kept here so the I/O failure
handling for the trust boundary has one home).
"""

import logging

import yaml

from relaypi.core.domain.entities.group_config import GroupConfig
from relaypi.core.domain.entities.inbound_message import InboundMessage
from relaypi.core.domain.interfaces.allowlist import Allowlist

logger = logging.getLogger(__name__)


class ConfigAllowlist(Allowlist):
    """Static allowlist: DM users + open/restricted groups. Restart to change.

    Gate rules:
      * DM (chat_type == "private"): allowed iff sender_user_id in dm_users.
      * Group: allowed iff the chat is configured; if open, any member; if
        restricted, only listed members.
      * Anything else (unknown group, channel post, etc.): dropped (fail closed).
    """

    def __init__(self, dm_users: set[int], groups: dict[int, GroupConfig]) -> None:
        self._dm_users = frozenset(dm_users)
        self._groups = dict(groups)

    def allows(self, msg: InboundMessage) -> bool:
        if msg.chat_type == "private":
            return msg.sender_user_id in self._dm_users
        group = self._groups.get(int(msg.chat_id))
        if group is None:
            return False  # unconfigured chat -> fail closed
        if group.mode == "open":
            return True
        return msg.sender_user_id in group.members


def load_allowlist(yaml_text: str) -> ConfigAllowlist:
    """Build a ConfigAllowlist from YAML config text.

    Decoupled from file I/O so it is trivially testable; the caller (config.py)
    reads the file and passes its text here. Expected YAML shape::

        dm_users: [987654321]
        groups:
          - id: -100111000
            mode: open
          - id: -100222000
            mode: restricted
            members: [987654321, 111222333]

    Args:
        yaml_text: The raw YAML config string.

    Returns:
        A ConfigAllowlist built from the config.
    """
    data = yaml.safe_load(yaml_text) or {}
    dm_users = {int(u) for u in data.get("dm_users", [])}
    groups: dict[int, GroupConfig] = {}
    for entry in data.get("groups", []):
        gid = int(entry["id"])
        mode = entry["mode"]
        if mode not in ("open", "restricted"):
            # Surface misconfiguration loudly at startup rather than silently
            # degrading to restricted/open behaviour (a typo like 'opne' or 'OPEN'
            # would otherwise change a group's trust posture invisibly).
            raise ValueError(
                f"invalid group mode {mode!r} for group {gid}; "
                "expected 'open' or 'restricted'"
            )
        members = frozenset(int(m) for m in entry.get("members", []))
        groups[gid] = GroupConfig(mode=mode, members=members)
    return ConfigAllowlist(dm_users=dm_users, groups=groups)


def load_allowlist_from_path(path: str) -> Allowlist:
    """Load an Allowlist from a YAML file, failing closed on any read error.

    Keeps file I/O (and its failure modes) out of Config and the application
    layer. A missing/unreadable file yields an empty allowlist (everything
    dropped) with a logged warning — fail-closed, never a crash.

    Args:
        path: Path to the allowlist YAML file.

    Returns:
        A ConfigAllowlist (typed as the Allowlist port).
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        logger.warning("could not read allowlist at %s (%s); failing closed", path, exc)
        text = ""
    return load_allowlist(text)
