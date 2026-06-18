"""Composition root — wire real adapters into a Relay.

This is the only place that knows about concrete adapter classes. Everything
else (Relay, routers, clients) depends on ports.

The per-chat PI client factory is defined here: it builds a
SubprocessStreamTransport + PIRpcClient for a given session path, with the HAL
project dir as cwd and ``-a`` to trust it for non-interactive RPC.
"""

import logging

from relaypi.config import Config
from relaypi.core.application.relay import Relay
from relaypi.core.domain.interfaces.agent_client import AgentClient
from relaypi.core.domain.interfaces.allowlist import Allowlist
from relaypi.infrastructure.adapters.pi_rpc_client import PIRpcClient
from relaypi.infrastructure.adapters.subprocess_stream_transport import (
    SubprocessStreamTransport,
)
from relaypi.infrastructure.adapters.telegramy_mcp_sender import TelegramyMCPSender
from relaypi.infrastructure.adapters.websocket_message_source import (
    WebSocketMessageSource,
)
from relaypi.infrastructure.allowlist_config import load_allowlist_from_path
from relaypi.infrastructure.session_router_impl import PerChatSessionRouter

logger = logging.getLogger(__name__)

# PI RPC invocation: --mode rpc, -a (trust the HAL project dir), --session <path>.
# cwd is set to the HAL project dir so PI loads AGENTS.md + .pi/SYSTEM.md +
# .pi/extensions/* for this profile. --session is load-bearing for isolation
# AND persistence (resumes the chat's history on restart; --no-session would
# discard both).
_PI_BASE_ARGV = ["--mode", "rpc", "-a"]
_SUBPROCESS_SHUTDOWN_TIMEOUT = 5.0


def build_pi_argv(pi_bin: str, session_path: str) -> list[str]:
    """Assemble the PI RPC invocation for one chat session.

    One home for "what flags PI needs" so adding/reordering a flag is a single
    edit (L2). ``-a`` trusts the HAL project dir; ``--session`` is load-bearing
    for both isolation and persistence.
    """
    return [pi_bin, *_PI_BASE_ARGV, "--session", session_path]


def create_relay(config: Config | None = None) -> Relay:
    """Build a fully-wired Relay from configuration."""
    cfg = config or Config()
    source = WebSocketMessageSource(cfg.telegramy_ws_url)
    sender = TelegramyMCPSender(cfg.telegramy_mcp_url)
    router = PerChatSessionRouter(
        session_root=cfg.session_dir,
        client_factory=_make_client_factory(cfg),
    )
    allowlist: Allowlist = load_allowlist_from_path(cfg.allowlist_path)
    return Relay(source=source, router=router, sender=sender, allowlist=allowlist)


def _make_client_factory(cfg: Config):
    """Build the async (session_path) -> AgentClient factory for the router."""

    async def factory(session_path: str) -> AgentClient:
        argv = build_pi_argv(cfg.pi_bin, session_path)
        transport = SubprocessStreamTransport(
            argv=argv,
            cwd=cfg.project_dir,
            shutdown_timeout=_SUBPROCESS_SHUTDOWN_TIMEOUT,
        )
        await transport.start()
        client = PIRpcClient(transport=transport)
        await client.start()
        logger.info("started PI client for session %s", session_path)
        return client

    return factory
