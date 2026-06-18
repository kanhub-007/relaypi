# RelayPI — Implementation Guide

Clean Architecture (Python flavor per AGENTS.md). The relay has no domain
logic, so `core/domain` holds interfaces + transport DTOs only; `core/application`
holds the `Relay` orchestrator; `infrastructure` holds the adapters; `startup`
wires them; `main.py` is the entry point.

Each step is grounded in PI's actual RPC protocol (`docs/rpc.md`, `docs/usage.md`)
and telegramy's actual surfaces. **Read `docs/development.md`'s "protocol traps"
section before writing the PI client (Step 5) — it lists four ways to get it wrong.**

> **Platform note:** the reference deployment is **Windows** (the owner's
> machine). Two Windows-specific issues are handled inline: (1) resolving the
> `pi` executable (it's a `.cmd` shim from the global npm install) and
> (2) signal handling (`loop.add_signal_handler` is unsupported on Windows).
> Search for `WINDOWS` in this file.

---

## Step 1: Project structure & dependencies

**File:** `pyproject.toml`
```toml
[project]
name = "relaypi"
version = "0.1.0"
requires-python = ">=3.12"
# No MCP SDK: telegramy's send tools are called via raw JSON-RPC over
# streamable-http, mirroring telegramy's own .pi/extensions/telegramy.ts.
dependencies = ["websockets>=12", "pyyaml>=6"]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "ruff", "black", "mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"   # async tests run without @pytest.mark.asyncio

[tool.black]
line-length = 88
```

**File:** `relaypi/__init__.py` (empty)

**Directory layout (one class per file per AGENTS.md §5):**
```
relaypi/
├── __init__.py
├── main.py                               # entry point
├── config.py                             # env + allowlist loading
├── core/
│   ├── domain/
│   │   ├── entities/
│   │   │   ├── inbound_message.py             # InboundMessage DTO
│   │   │   ├── formatted_prompt.py            # FormattedPrompt DTO
│   │   │   ├── outbound_reply.py              # OutboundReply DTO
│   │   │   └── group_config.py                # GroupConfig DTO
│   │   └── interfaces/
│   │       ├── message_source.py              # MessageSource (contract 1)
│   │       ├── agent_client.py                # AgentClient  (contract 2)
│   │       ├── message_sender.py              # MessageSender (contract 3)
│   │       ├── allowlist.py                   # Allowlist (policy)
│   │       └── session_router.py              # SessionRouter (routing)
│   └── application/
│       ├── parse.py                           # parse_inbound()
│       ├── format_prompt.py                   # format_prompt()
│       └── relay.py                           # Relay orchestrator
├── infrastructure/
│   ├── adapters/
│   │   ├── websocket_message_source.py        # telegramy WS subscriber
│   │   ├── pi_rpc_client.py                   # PI RPC subprocess client
│   │   └── telegramy_mcp_sender.py            # telegramy MCP send client
│   ├── allowlist_config.py                    # static-config Allowlist impl
│   └── session_router_impl.py                 # per-chat PI process pool
└── startup/
    └── factory.py                             # create_relay() composition root

config/
└── allowlist.yaml                         # DM users + open/restricted groups

hal/                                       # the HAL "project dir" (PI profile)
├── AGENTS.md                              # context file (developer constitution)
├── .pi/
│   ├── SYSTEM.md                          # HAL system prompt
│   └── extensions/
│       ├── telegramy.ts                   # MCP bridge (copy from telegramy repo)
│       ├── kapsula.ts                     # same pattern, different URL
│       ├── finbar.ts                      # same pattern, different URL
│       └── webdown.ts                     # same pattern, different URL
└── sessions/                              # per-chat .jsonl (PI-owned)

tests/
├── fakes/                                 # in-memory fakes (Classical school)
├── application/                           # pure-function + Relay tests
└── infrastructure/                        # adapter tests with fake subprocess
```

**Verify:** `pip install -e ".[dev]"` succeeds; `pytest --collect-only` finds no errors.

---

## Step 2: Transport DTOs + interfaces

**File:** `relaypi/core/domain/entities/inbound_message.py`
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    chat_id: str
    chat_type: str                 # "private" | "group" | "supergroup" | ...
    sender_user_id: int            # allowlist key
    sender_username: str | None    # preferred for prefix
    sender_first_name: str | None  # fallback for prefix
    text: str
```

**File:** `relaypi/core/domain/entities/formatted_prompt.py`
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FormattedPrompt:
    text: str   # "[from={username}] {message}"
```

**File:** `relaypi/core/domain/entities/outbound_reply.py`
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class OutboundReply:
    chat_id: str
    text: str
```

**File:** `relaypi/core/domain/entities/group_config.py`
```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GroupConfig:
    mode: str                                      # "open" | "restricted"
    members: frozenset[int] = field(default_factory=frozenset)  # only when restricted
```

**File:** `relaypi/core/domain/interfaces/message_source.py`
```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class MessageSource(ABC):
    """Filtered inbound event stream from telegramy (contract 1)."""

    @abstractmethod
    def events(self) -> AsyncIterator[dict]: ...
```

**File:** `relaypi/core/domain/interfaces/agent_client.py`
```python
from abc import ABC, abstractmethod


class AgentClient(ABC):
    """One PI RPC subprocess (contract 2). Serialized externally per-chat."""

    @abstractmethod
    async def prompt_and_collect(self, message: str) -> str: ...
    @abstractmethod
    async def abort(self) -> None: ...
    @abstractmethod
    def is_alive(self) -> bool: ...
    @abstractmethod
    async def stop(self) -> None: ...
```

**File:** `relaypi/core/domain/interfaces/message_sender.py`
```python
from abc import ABC, abstractmethod


class MessageSender(ABC):
    """Outbound send to Telegram via telegramy MCP (contract 3)."""

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...
```

**File:** `relaypi/core/domain/interfaces/allowlist.py`
```python
from abc import ABC, abstractmethod

from relaypi.core.domain.entities.inbound_message import InboundMessage


class Allowlist(ABC):
    """Trust gate. Pure: no I/O."""

    @abstractmethod
    def allows(self, msg: InboundMessage) -> bool: ...
```

**File:** `relaypi/core/domain/interfaces/session_router.py`
```python
from abc import ABC, abstractmethod

from relaypi.core.domain.interfaces.agent_client import AgentClient


class SessionRouter(ABC):
    """Routes chat_id -> a live AgentClient, (re)starting PI as needed."""

    @abstractmethod
    async def get_or_create(self, chat_id: str) -> AgentClient: ...
    @abstractmethod
    async def stop_all(self) -> None: ...
```

**Verify:** `ruff check relaypi/core/domain/` clean.

---

## Step 3: Message parser + formatter (pure functions)

**File:** `relaypi/core/application/parse.py`
```python
from relaypi.core.domain.entities.inbound_message import InboundMessage


def parse_inbound(event: dict) -> InboundMessage | None:
    """Extract an InboundMessage from a telegramy WS event, or None to skip."""
    msg = event.get("message")
    if not msg:
        return None
    text = (msg.get("text") or "").strip()
    if not text:
        return None
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    return InboundMessage(
        chat_id=str(chat.get("id")),
        chat_type=str(chat.get("type", "")),
        sender_user_id=int(sender.get("id", 0)),
        sender_username=sender.get("username"),
        sender_first_name=sender.get("first_name"),
        text=text,
    )
```

**File:** `relaypi/core/application/format_prompt.py`
```python
from relaypi.core.domain.entities.formatted_prompt import FormattedPrompt
from relaypi.core.domain.entities.inbound_message import InboundMessage


def format_prompt(msg: InboundMessage) -> FormattedPrompt:
    """Display-only prefix. chat_id is deliberately NOT included."""
    name = msg.sender_username or msg.sender_first_name or "anonymous"
    return FormattedPrompt(text=f"[from={name}] {msg.text}")
```

**Verify:** `pytest tests/application/test_parse_and_format.py` — assert:
- username present → `[from=koena]`
- username absent, first_name present → `[from=X]`
- both absent → `[from=anonymous]`
- non-message event / empty text → `parse_inbound` returns None

---

## Step 4: Allowlist (policy)

**File:** `relaypi/infrastructure/allowlist_config.py`
```python
from relaypi.core.domain.entities.group_config import GroupConfig
from relaypi.core.domain.entities.inbound_message import InboundMessage
from relaypi.core.domain.interfaces.allowlist import Allowlist


class ConfigAllowlist(Allowlist):
    """Static allowlist loaded from config (restart to change)."""

    def __init__(self, dm_users: set[int], groups: dict[int, GroupConfig]) -> None:
        self._dm_users = frozenset(dm_users)
        self._groups = dict(groups)

    def allows(self, msg: InboundMessage) -> bool:
        if msg.chat_type == "private":
            return msg.sender_user_id in self._dm_users
        grp = self._groups.get(int(msg.chat_id))
        if grp is None:
            return False
        if grp.mode == "open":
            return True
        return msg.sender_user_id in grp.members
```

**File:** `config/allowlist.yaml` (shape):
```yaml
dm_users: [987654321]
groups:
  - id: -100111000
    mode: open
  - id: -100222000
    mode: restricted
    members: [987654321, 111222333]
```

**Verify:** `pytest tests/infrastructure/test_allowlist.py` — the four gate cases from `02-scenarios.md` (DM allow/deny, open group, restricted member/non-member, unknown group).

---

## Step 5: PI RPC client (the hardest part — read carefully)

**This step contains four protocol traps. Get them wrong and the relay hangs,
deadlocks, or loses history. They are documented in `docs/development.md`.**

The client must:
1. Spawn PI with **cwd = HAL project dir**, `-a` (trust it), and an explicit
   **per-chat session file** (`--session <path>`).
2. Run a **background reader** that demuxes stdout into three streams by type:
   `response` → resolve the matching command future by `id`;
   `extension_ui_request` → dispatch to the approval handler (**never** ignored);
   everything else → the current turn's event queue.
3. Send commands with an `id` and **await the matching `response`** before
   waiting for events — otherwise a rejected prompt hangs forever.
4. Track **liveness** (reader task ended = subprocess dead) so the router can
   restart; bound `proc.wait()` with a timeout; **bound each turn** so a dead
   PI mid-turn doesn't hold the per-chat lock forever.

**File:** `relaypi/infrastructure/adapters/pi_rpc_client.py`
```python
"""PI RPC client — one subprocess per chat, with a demuxing reader."""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

TURN_TIMEOUT = 600.0   # seconds; a single agent turn should never exceed this
ABORT_TIMEOUT = 15.0   # seconds to wait for PI to ack an abort before killing it


class PIRpcClient:
    def __init__(self, pi_bin: str, project_dir: str, session_path: str) -> None:
        self._pi_bin = pi_bin
        self._project_dir = project_dir
        self._session_path = session_path
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._event_queue: asyncio.Queue[dict] | None = None  # current turn
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self._pi_bin,
            "--mode", "rpc",
            "-a",                          # trust the HAL project dir (non-interactive)
            "--session", self._session_path,   # load-bearing: isolation + persistence
            cwd=self._project_dir,         # PI loads AGENTS.md + .pi/ from here
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        self._alive = True
        self._reader_task = asyncio.create_task(self._read_loop())

    async def prompt_and_collect(self, message: str) -> str:
        """Send a prompt, await its ack, stream to agent_end, return final text.

        On turn timeout, aborts the runaway turn (see ``abort``) so the chat
        is not bricked, then re-raises. The warm process is preserved when
        possible; abort only kills the process if PI is truly wedged.
        """
        resp = await self._send_command({"type": "prompt", "message": message})
        if not resp.get("success"):
            raise RuntimeError(f"PI rejected prompt: {resp.get('error')}")

        self._event_queue = asyncio.Queue()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        self._event_queue.get(), timeout=TURN_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    # Stuck turn (infinite tool loop, hung API call). Cancel it
                    # so PI returns to idle and the next message isn't rejected
                    # as "prompt-while-streaming". abort() keeps the process
                    # warm unless PI can't even ack.
                    await self.abort()
                    raise
                if event.get("type") == "agent_end":
                    break
        finally:
            self._event_queue = None

        # Cleaner than reassembling text_delta fragments; robust to thinking/tool blocks.
        return await self._get_last_assistant_text()

    async def abort(self) -> None:
        """Cancel the current turn, escalating to kill if PI is wedged.

        Tries the graceful ``abort`` RPC first — PI stops the turn, returns to
        idle, and the warm process + session are preserved. If PI cannot ack
        within ``ABORT_TIMEOUT`` the process is truly wedged and is killed;
        the router restarts a fresh one at the same session file on next
        access. Either outcome prevents a bricked chat.
        """
        try:
            await asyncio.wait_for(
                self._send_command({"type": "abort"}), timeout=ABORT_TIMEOUT
            )
        except Exception as exc:
            logger.warning("abort failed/timed out, killing PI subprocess: %s", exc)
            await self.stop()

    async def _get_last_assistant_text(self) -> str:
        resp = await self._send_command({"type": "get_last_assistant_text"})
        return (resp.get("data") or {}).get("text") or ""

    async def _send_command(self, cmd: dict) -> dict:
        req_id = self._next_id = self._next_id + 1
        cmd = {"id": req_id, **cmd}
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[req_id] = fut
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((json.dumps(cmd) + "\n").encode())
        await self._proc.stdin.drain()
        return await fut

    async def _read_loop(self) -> None:
        """Strict LF framing (rpc.md). Demux by message type."""
        buffer = b""
        assert self._proc and self._proc.stdout
        try:
            while True:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break  # subprocess exited
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.removesuffix(b"\r")
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    await self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("PI reader loop crashed")
        finally:
            self._alive = False
            # Unblock anyone waiting on a command response or the event queue.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("PI subprocess exited"))
            self._pending.clear()
            if self._event_queue is not None:
                self._event_queue.put_nowait({"type": "agent_end"})  # unblock the turn

    async def _dispatch(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "response":
            fut = self._pending.pop(msg.get("id"), None)
            if fut and not fut.done():
                fut.set_result(msg)
        elif t == "extension_ui_request":
            await self._handle_ui_request(msg)   # MUST answer — else PI blocks forever
        else:
            # event (agent_start, message_update, tool_execution_*, compaction_*, ...)
            if self._event_queue is not None:
                self._event_queue.put_nowait(msg)

    async def _handle_ui_request(self, req: dict) -> None:
        """MVP: auto-respond per policy. Fire-and-forget methods need no reply."""
        method = req.get("method")
        rid = req.get("id")
        if method in ("select", "input", "editor"):
            await self._send_raw({"type": "extension_ui_response", "id": rid, "value": ""})
        elif method == "confirm":
            await self._send_raw({"type": "extension_ui_response", "id": rid, "confirmed": True})
        # notify / setStatus / setWidget / setTitle / set_editor_text: no response.

    async def _send_raw(self, obj: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self._proc.stdin.drain()

    async def stop(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._alive = False
```

**Common mistakes (all real protocol traps):**
- Splitting stdout on anything but `\n` (rpc.md: readline-style readers split on
  U+2028/U+2029 and corrupt JSON strings).
- Waiting for `agent_end` without first awaiting the `response` → hangs on rejection.
- Ignoring `extension_ui_request` → PI blocks forever, turn never ends.
- Using `--session-dir` only (no explicit file) → every chat resumes the *same*
  most-recent session (no isolation).
- No `TURN_TIMEOUT` → a dead or runaway PI mid-turn holds the per-chat lock
  forever. On timeout you MUST `abort` (not just release the lock) — otherwise
  PI keeps streaming and the next prompt is rejected as "streaming", bricking
  the chat. If `abort` itself goes unacked, escalate to `stop()` (kill); the
  router restarts from the persisted session file.

**Verify:** `pytest tests/infrastructure/test_pi_rpc_client.py` using a **fake
subprocess** — a small async helper that writes canned JSONL lines to one end
of a pipe and reads commands from the other. Assert:
- `prompt_and_collect` returns the text from a following `get_last_assistant_text` response
- a `response` with `success:false` raises (does not hang)
- an injected `extension_ui_request {method:confirm}` produces an `extension_ui_response {confirmed:true}` and the turn still completes
- closing the fake stdout (simulating crash) → `is_alive()` becomes False, the
  pending turn's `agent_end` is synthesized (no permanent hang)
- `spawn` was called with `-a`, `--session <path>`, and `cwd=<project_dir>` (assert on argv)
- **turn timeout → abort then re-raise**: feed no `agent_end` and fast-forward
  past `TURN_TIMEOUT`; assert an `abort` command was written to PI's stdin and
  `prompt_and_collect` raised `asyncio.TimeoutError`
- **wedge escalation**: make `abort` go unacked past `ABORT_TIMEOUT`; assert
  the subprocess was killed (`is_alive()==False`) so the router will restart it

---

## Step 6: Session router + telegramy sender

**File:** `relaypi/infrastructure/session_router_impl.py`
```python
from pathlib import Path

from relaypi.core.domain.interfaces.agent_client import AgentClient
from relaypi.core.domain.interfaces.session_router import SessionRouter
from relaypi.infrastructure.adapters.pi_rpc_client import PIRpcClient


class PerChatSessionRouter(SessionRouter):
    """One PI process per chat, isolated by --session <path>. Restarts on death."""

    def __init__(self, pi_bin: str, project_dir: str, session_root: str) -> None:
        self._pi_bin = pi_bin
        self._project_dir = project_dir
        self._root = Path(session_root)
        self._clients: dict[str, AgentClient] = {}

    async def get_or_create(self, chat_id: str) -> AgentClient:
        client = self._clients.get(chat_id)
        if client is not None and client.is_alive():
            return client
        # First time, or previous process died → (re)start at the same path.
        self._root.mkdir(parents=True, exist_ok=True)
        session_path = str(self._root / f"chat_{self._safe(chat_id)}.jsonl")
        new = PIRpcClient(self._pi_bin, self._project_dir, session_path)
        await new.start()
        self._clients[chat_id] = new
        return new

    @staticmethod
    def _safe(chat_id: str) -> str:
        # Group ids are negative; make a filesystem-safe token.
        return chat_id.replace("-", "g")

    async def stop_all(self) -> None:
        for c in self._clients.values():
            await c.stop()
        self._clients.clear()
```

**File:** `relaypi/infrastructure/adapters/telegramy_mcp_sender.py`

The relay calls telegramy's MCP send tools over streamable-http. **Mirror
telegramy's own `.pi/extensions/telegramy.ts` `McpHttpClient`** (initialize →
capture `mcp-session-id` → `notifications/initialized` → `tools/call`). No MCP
SDK; raw JSON-RPC over `httpx`.

```python
"""Outbound via telegramy's MCP send tools (contract 3).

Mirrors the McpHttpClient in telegramy's .pi/extensions/telegramy.ts:
initialize handshake, capture mcp-session-id, then tools/call.
"""
import json
import logging

import httpx

from relaypi.core.domain.interfaces.message_sender import MessageSender

logger = logging.getLogger(__name__)


class TelegramyMCPSender(MessageSender):
    def __init__(self, mcp_url: str, timeout: float = 30.0) -> None:
        self._url = mcp_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
        self._session_id: str | None = None
        self._req_id = 0

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._ensure_initialized()
        await self._call("tools/call", {
            "name": "send_message",
            "arguments": {"chat_id": chat_id, "text": text},
        })

    async def _ensure_initialized(self) -> None:
        if self._session_id is not None:
            return
        resp = await self._client.post(self._url, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "relaypi", "version": "0.1.0"},
            },
        }, headers=self._headers(init=True))
        resp.raise_for_status()
        self._session_id = resp.headers.get("mcp-session-id")
        await self._client.post(self._url, json={
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        }, headers=self._headers())

    async def _call(self, method: str, params: dict) -> dict:
        self._req_id += 1
        resp = await self._client.post(self._url, json={
            "jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params,
        }, headers=self._headers())
        resp.raise_for_status()
        data = self._parse(resp.text)
        if "error" in data:
            raise RuntimeError(f"telegramy MCP error: {data['error']}")
        return data.get("result", {})

    def _headers(self, init: bool = False) -> dict:
        h = {"Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if self._session_id and not init:
            h["mcp-session-id"] = self._session_id
        return h

    @staticmethod
    def _parse(text: str) -> dict:
        # FastMCP streamable-http returns SSE; plain JSON is also accepted.
        if text.startswith("{"):
            return json.loads(text)
        for line in text.split("\n"):
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return {}

    async def close(self) -> None:
        await self._client.aclose()
```

> Add `httpx` to `pyproject.toml` dependencies.

**Verify:** `pytest tests/infrastructure/test_session_router.py` — two chat ids → two distinct session paths and two clients; a client whose `is_alive()` is False is restarted on next `get_or_create`.

---

## Step 7: The Relay orchestrator (use case) + WS source

**File:** `relaypi/core/application/relay.py`
```python
"""RelayPI use case: trust -> route -> format -> prompt -> capture -> send."""

import asyncio
import logging

from relaypi.core.application.format_prompt import format_prompt
from relaypi.core.application.parse import parse_inbound
from relaypi.core.domain.entities.inbound_message import InboundMessage
from relaypi.core.domain.interfaces.allowlist import Allowlist
from relaypi.core.domain.interfaces.message_sender import MessageSender
from relaypi.core.domain.interfaces.message_source import MessageSource
from relaypi.core.domain.interfaces.session_router import SessionRouter

logger = logging.getLogger(__name__)


class Relay:
    def __init__(
        self,
        source: MessageSource,
        router: SessionRouter,
        sender: MessageSender,
        allowlist: Allowlist,
    ) -> None:
        self._source = source
        self._router = router
        self._sender = sender
        self._allowlist = allowlist
        self._chat_locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = False

    async def run(self) -> None:
        """Read the WS without blocking; dispatch each message as its own task."""
        async for event in self._source.events():
            msg = parse_inbound(event)
            if msg is None:
                continue
            if not self._allowlist.allows(msg):
                logger.info("dropped message from %s in %s", msg.sender_user_id, msg.chat_id)
                continue
            task = asyncio.create_task(self._handle(msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _handle(self, msg: InboundMessage) -> None:
        # Per-chat serialization: never prompt a streaming PI.
        lock = self._chat_locks.setdefault(msg.chat_id, asyncio.Lock())
        async with lock:
            try:
                client = await self._router.get_or_create(msg.chat_id)
                prompt = format_prompt(msg)
                text = await client.prompt_and_collect(prompt.text)
                await self._sender.send_message(msg.chat_id, text)
            except Exception:
                # Never let one message's failure kill the relay or leave the
                # user in silence. Report the error back to the chat.
                logger.exception("failed to handle message in %s", msg.chat_id)
                try:
                    await self._sender.send_message(
                        msg.chat_id, "⚠️ Something went wrong processing that. Try again."
                    )
                except Exception:
                    logger.exception("also failed to send error reply")

    async def drain(self) -> None:
        """Test helper: run to completion against a finite source."""
        await self.run()

    async def stop(self) -> None:
        self._stopping = True
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._router.stop_all()
        await self._sender.close()   # close the MCP httpx client cleanly
```

**File:** `relaypi/infrastructure/adapters/websocket_message_source.py`
```python
"""Filtered inbound from telegramy (contract 1: selective subscriptions).

Subscribe with events=["message"] ONLY — DM chat_ids are not known until the
first message arrives, so a chats filter would drop legitimate DMs. The
allowlist gates which messages actually get processed.
"""
import json
from collections.abc import AsyncIterator

import websockets


class WebSocketMessageSource:
    def __init__(self, url: str) -> None:
        self._url = url

    async def events(self) -> AsyncIterator[dict]:
        async with websockets.connect(self._url) as ws:
            await ws.send(json.dumps({"type": "subscribe", "events": ["message"]}))
            async for raw in ws:
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue
```

**Verify:** `pytest tests/application/test_relay.py` — all Verify blocks from `02-scenarios.md` using the fakes. Include a test that a raising `AgentClient` produces an error reply via the sender (does not crash the relay).

---

## Step 8: Composition root + entry point

**File:** `relaypi/config.py`
```python
"""Load relay configuration from env vars + allowlist.yaml."""
import os
import shutil
from pathlib import Path

import yaml

from relaypi.core.domain.entities.group_config import GroupConfig


class Config:
    def __init__(self) -> None:
        self.telegramy_ws_url = os.environ.get("RELAYPI_WS_URL", "ws://localhost:8765")
        self.telegramy_mcp_url = os.environ.get("RELAYPI_MCP_URL", "http://localhost:8005/mcp")
        # WINDOWS: `pi` is a .cmd shim; resolve the full path so
        # create_subprocess_exec finds it. Override with RELAYPI_PI_BIN if needed.
        self.pi_bin = os.environ.get("RELAYPI_PI_BIN") or shutil.which("pi") or "pi"
        self.project_dir = os.environ.get("RELAYPI_PROJECT_DIR", "hal")
        self.session_dir = os.environ.get("RELAYPI_SESSION_DIR", "hal/sessions")
        self.allowlist_path = os.environ.get("RELAYPI_ALLOWLIST", "config/allowlist.yaml")
        self.dm_users, self.groups = _load_allowlist(self.allowlist_path)


def _load_allowlist(path: str) -> tuple[set[int], dict[int, GroupConfig]]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    dm = {int(u) for u in data.get("dm_users", [])}
    groups: dict[int, GroupConfig] = {}
    for g in data.get("groups", []):
        gid = int(g["id"])
        mode = g["mode"]
        members = frozenset(int(m) for m in g.get("members", []))
        groups[gid] = GroupConfig(mode=mode, members=members)
    return dm, groups
```

**Environment variables:**
| Var | Default | Purpose |
|-----|---------|---------|
| `RELAYPI_WS_URL` | `ws://localhost:8765` | telegramy WebSocket |
| `RELAYPI_MCP_URL` | `http://localhost:8005/mcp` | telegramy MCP send endpoint |
| `RELAYPI_PI_BIN` | `shutil.which("pi")` | PI executable path (Windows: the .cmd shim) |
| `RELAYPI_PROJECT_DIR` | `hal` | HAL project dir (AGENTS.md + .pi/) |
| `RELAYPI_SESSION_DIR` | `hal/sessions` | per-chat .jsonl root |
| `RELAYPI_ALLOWLIST` | `config/allowlist.yaml` | allowlist config file |

**File:** `relaypi/startup/factory.py`
```python
from relaypi.config import Config
from relaypi.core.application.relay import Relay
from relaypi.infrastructure.adapters.telegramy_mcp_sender import TelegramyMCPSender
from relaypi.infrastructure.adapters.websocket_message_source import WebSocketMessageSource
from relaypi.infrastructure.allowlist_config import ConfigAllowlist
from relaypi.infrastructure.session_router_impl import PerChatSessionRouter


def create_relay() -> Relay:
    cfg = Config()
    source = WebSocketMessageSource(cfg.telegramy_ws_url)
    router = PerChatSessionRouter(cfg.pi_bin, cfg.project_dir, cfg.session_dir)
    sender = TelegramyMCPSender(cfg.telegramy_mcp_url)
    allowlist = ConfigAllowlist(cfg.dm_users, cfg.groups)
    return Relay(source, router, sender, allowlist)
```

**File:** `relaypi/main.py`
```python
import asyncio
import logging
import sys

from relaypi.startup.factory import create_relay


async def main() -> None:
    relay = create_relay()
    # WINDOWS: loop.add_signal_handler is unsupported. Rely on KeyboardInterrupt
    # (raised by Ctrl+C / console close) instead. On POSIX you may add signal
    # handlers; guarded here so the same code runs on both.
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
```

**Verify:** end-to-end smoke: `python -m relaypi.main` with telegramy + PI + MCP services running; send a Telegram message, observe a reply.

---

## Step 9: HAL project dir (PI profile)

PI has **no `--config-dir` flag**. A "profile" is a project directory that PI
loads from its cwd: `AGENTS.md` (context file), `.pi/SYSTEM.md` (system prompt),
and `.pi/extensions/*.ts` (capabilities). The relay runs PI with
`cwd=<HAL project dir>` and `-a` (trust it for non-interactive runs).

**File:** `hal/AGENTS.md` — copy the developer constitution (`C:\HAL\AGENTS.md`).
PI loads this as a context file (usage.md §94). Case-sensitive filename.

**File:** `hal/.pi/SYSTEM.md`
```markdown
You are HAL, a personal assistant operating through Telegram.

Messages arrive via RPC prompt with a [from=username] prefix (display only).
The channel and chat identity are handled outside your context — you do not
need to know chat ids. Your final text reply is captured and delivered for you.

Available tools (registered by extensions in .pi/extensions/):
- kapsula: search, upload_document (memory)
- finbar: fetch_prices, backtest, apply_indicators (trading)
- webdown: generate_markdown, search_web, aggregate_rss (web)
- telegramy: send_message, send_photo, send_file (media — optional; text replies
  are sent for you by the relay)
- filesystem: read, write, edit, bash (built-in)

Commands (forwarded as prompts by the relay for now):
- /reset — forget current conversation and start fresh
- /compact — summarize old conversation to free context
```

**Directory:** `hal/.pi/extensions/` — one TypeScript extension per MCP service.
**Copy `telegramy.ts` from the telegramy repo** (`C:\HAL\Github\telegramy\.pi\extensions\telegramy.ts`)
as the template. For kapsula/finbar/webdown, duplicate it and change the MCP URL
resolution (env var name + default port: kapsula=8002, finbar=8003, webdown=8004).

Each extension follows the same proven pattern (see telegramy's for the full
reference): on `session_start`, connect to its MCP server over streamable-http,
discover tools via `tools/list`, register each via `pi.registerTool()` with a
TypeBox schema converted from the tool's `inputSchema`.

> **There is no `mcp.json`.** PI's MCP integration is entirely via these
> extensions. This is why telegramy ships `.pi/extensions/telegramy.ts` rather
> than a config file.

**Trust:** `-a` trusts the HAL project dir for each run (required because RPC
mode is non-interactive and won't show a trust prompt — without it, `.pi/`
resources silently don't load). Alternatively, pre-trust the dir once via an
interactive `pi` session in `hal/`, which saves the decision.

**Verify:**
```bash
cd hal
pi -a --print "hello"        # loads SYSTEM.md + extensions, prints a reply, exits
```
If the extensions connect, you'll see their `notify` messages ("telegramy:
Connected, N tools discovered"). If not, the MCP services aren't running.

---

## Step 10: Documentation (README + docs/)

The relay is a small, seam-critical service — it must be legible on its own.

**File:** `README.md` — must include:
- One-paragraph "what and why" (binding layer between telegramy and PI).
- **The architecture sketch** — copy the diagram + four-contract table from
  `specs/.../01-story.md` "Where the Relay Fits".
- Quickstart: prerequisites (telegramy running, PI installed, MCP services up),
  config (`config/allowlist.yaml`, env vars table from Step 8),
  `pip install -e .`, `python -m relaypi.main`.
- The four contracts listed explicitly.
- Windows note (pi resolution, signals).
- Pointer to `docs/`.

**Directory:** `docs/`
```
docs/
├── architecture.md      # see 05-architecture.md (ADRs): three-service model,
│                        #   separation of concerns, why not embed in telegramy,
│                        #   Option B delivery, per-chat model, HAL profile
├── usage.md             # how to run, env vars, logs, troubleshooting
├── configuration.md     # allowlist.yaml (open vs restricted groups, DM users),
│                        #   HAL project dir layout, session storage, PI extensions
└── development.md       # testing (Classical school + fakes), lint/format/typecheck,
                        #   and the FOUR PROTOCOL TRAPS (below)
```

**`docs/development.md` — the four protocol traps** (the most likely future-bug
source; lift verbatim from Step 5's "Common mistakes"):
1. **LF-only framing** — split PI stdout on `\n` only; readline-style readers
   split on U+2028/U+2029 and corrupt JSON strings.
2. **Await `response` before `agent_end`** — every command returns a `response`
   with `success`/`id`; a rejected prompt never emits `agent_end`, so waiting
   for it hangs forever.
3. **Never ignore `extension_ui_request`** — dialog requests block PI until
   answered; an unhandled one deadlocks the turn.
4. **Explicit `--session <path>` for isolation** — `--session-dir` alone makes
   every chat resume the same most-recent session file.

**Verify:** a new reader can, from the README alone, (a) say what the relay
does, (b) draw where it sits between telegramy and PI, and (c) start it.

---

## Step 11: Process supervision (Slice 2)

**File:** `docker-compose.yml` or systemd unit.

Run telegramy + MCP services + relay together; the relay supervises its own PI
subprocesses (Step 5 liveness + Step 6 restart); the OS supervises the relay.
On relay restart, PI resumes each chat from its persisted `chat_{id}.jsonl`.
