# HAL Relay — Architecture Research & Design Decisions

> **Date:** 2026-06-17
> **Context:** Designing the bridge between Telegram and PI for HAL, a personal AI assistant with coding capabilities.

---

## 1. Starting Point: The HAL Ecosystem

Before this discussion, HAL had several independent components that needed connecting:

```
C:\HAL\Github\
├── pi (global install)     # Coding agent harness — the AI brain
├── telegramy/              # Telegram bridge service (Python, Clean Architecture)
│   ├── Polling/webhook → parse updates → WebSocket broadcast
│   └── MCP server: send_message, send_file, send_photo, etc.
├── kapsula/                # Memory/knowledge system (Python, Clean Architecture)
│   └── MCP server: document upload, hybrid search, LLM query planning
├── finbar/                 # Trading analysis engine (Python, Clean Architecture)
│   └── MCP server: backtesting, indicators, market data, strategy optimization
├── webdown/                # Web content extraction (Python, Clean Architecture)
│   └── MCP server: markdown generation, RSS aggregation, sitemap, web search
├── pi_extensions/          # PI tool extensions (TypeScript)
│   └── Review commands, TDD driver, spec writer, safety guards
└── openclaw/               # Reference architecture (TypeScript, multi-channel agent platform)
```

Each service follows Clean Architecture with domain/application/infrastructure/presentation layers. Each has its own MCP server for AI agent integration. telegramy additionally has a WebSocket server for real-time inbound message delivery.

**The gap:** PI could use all MCP tools, but had no way to receive Telegram messages. Starting PI in a terminal worked for local use, but there was no path for `Telegram message → PI receives it → PI responds → Telegram`.

---

## 2. OpenClaw Analysis: What We Studied

We spent significant time analyzing how OpenClaw (an open-source multi-channel AI agent platform) solves the same problem. OpenClaw has:

### OpenClaw's Architecture (What We Looked At)

```
Channel plugins (Telegram, Discord, WhatsApp, Slack)
        │
        ▼
Channel Turn Kernel (runChannelInboundEvent)
        │
        ▼
Auto-Reply Dispatch (dispatchReplyFromConfig)  ← 3K+ lines
        │
        ▼
Agent Runner (runEmbeddedAgent)  ← 4K+ lines
        │
        ▼
Harness Layer (AgentHarness interface)
        │
        ├── "openclaw" harness (built-in PI equivalent)
        ├── "codex" harness (Codex SDK bridge)
        └── "copilot" harness (Copilot SDK bridge)
```

Key subsystems we studied:
- **Harness selection** (`src/agents/harness/selection.ts`): Routes agent runs to pluggable backends
- **Session management** (`src/config/sessions/`, `src/auto-reply/reply/session.ts`): Persistent transcripts per conversation
- **Tool policy gate** (`src/agents/agent-tools.before-tool-call.ts`): Before-tool-call hooks, approvals, loop detection
- **Sub-agent spawning** (`src/agents/subagent-spawn.ts`): Parallel agent runs with steering queue
- **Channel adapters** (`extensions/telegram/`): 150+ files for Telegram integration
- **Command system** (`src/auto-reply/reply/commands*.ts`): Inline /reset, /model, /think parsing
- **Context engine** (`src/context-engine/`): Bootstrap files, memory injection, compaction
- **Cron** (`src/cron/`): Scheduled background tasks
- **Native hook relay** (`src/agents/harness/native-hook-relay.ts`): HTTP bridge for external harness → OpenClaw hooks

### Why We Didn't Copy OpenClaw

OpenClaw is a **multi-user, multi-channel, multi-harness platform** with:
- Plugin registries and discovery
- Auth profile rotation and credential management
- Twenty channel adapters
- Sub-agent spawning with complex lifecycle management
- Process-level diagnostics and tracing
- ~1800 files in `src/agents/` alone

HAL is a **single-user, single-channel, single-agent assistant**. Copying OpenClaw's orchestrator pattern would mean reimplementing session management, compaction, context assembly, and tool policies — all things PI already has. The cost would be massive and the benefit zero.

**What we did take from OpenClaw:** The channel adapter pattern. The insight that the channel layer should be thin — transport in, transport out, nothing more. OpenClaw's `bot-message-dispatch.ts` feeds into a shared kernel that feeds into the agent. HAL's relay feeds into PI's stdin. Same pattern, different scale.

---

## 3. Design Alternatives Considered

### Option A: HAL as Full Orchestrator (Rejected)

The first proposal was to build HAL as an orchestrator layer between Telegram and PI:
- Session store (SQLite) for transcripts
- Context builder for prompt assembly
- Compaction logic for context window management
- Command parser for /reset, /model, /think
- PI runner as a per-turn subprocess

**Why rejected:** This reimplements PI's existing capabilities. PI already has sessions, compaction, tool policies, and MCP integration. Building a parallel orchestrator creates two sources of truth for session state, two compaction implementations, and ongoing maintenance burden.

### Option B: Skip telegramy, Direct Bot API (Rejected)

Replace telegramy with a direct `python-telegram-bot` integration in HAL.

**Why rejected:** telegramy already has validation, retry, Markdown formatting, inline keyboard handling, WebSocket for real-time events, and MCP tools for sending. Reimplementing all of that is more work than building the relay.

### Option C: Extend telegramy with PI Consumer (Rejected)

Add PI invocation logic directly into telegramy.

**Why rejected:** Violates telegramy's design as a bridge service. Couples the bridge to the agent. Makes it harder to add other channels or swap agents.

### Option D: Thin Relay (Selected)

A ~30-line script that connects telegramy WebSocket to PI stdin. PI handles everything else through its existing MCP tools.

**Why selected:** Minimal code. No new state. No duplication of PI's capabilities. PI is the single source of truth for sessions, context, and tool execution.

---

## 4. Decision: PI RPC Mode + Thin Relay

### Core Principle

**PI is the agent. The relay is a channel adapter. PI's RPC protocol gives us structured communication.**

```
Telegram ←→ telegramy ←WS→ relay ←RPC→ PI (HAL config)
                  ↑                        │
                  └──── MCP tools ─────────┘
                       (PI sends replies)
```

### Why RPC Mode Instead of Stdin

PI exposes a full JSON-RPC protocol over stdin/stdout (`pi --mode rpc`). This gives the relay structured two-way communication:

- **`prompt` command** — send a message to PI with streaming behavior control (`steer`/`followUp` during active runs)
- **`abort` command** — cancel the current agent operation
- **Streaming events** — `message_update` (text_delta, thinking_delta, toolcall_delta), `tool_execution_start/update/end`
- **Lifecycle events** — `agent_start`, `agent_end`, `turn_start`, `turn_end`
- **Session commands** — `new_session`, `compact`, `get_state`, `get_messages`
- **Model control** — `set_model`, `set_thinking_level`, `cycle_model`
- **Error handling** — structured error responses, auto-retry events
- **Extension UI protocol** — `select`, `confirm`, `input` dialogs for approval flows

The RPC protocol eliminates all the fragility concerns with raw stdin:
- Status visibility: `get_state` tells you if PI is streaming, compacting, idle
- Delivery guarantees: structured command/response with error codes
- Concurrent sessions: each chat gets its own RPC session via `new_session`
- Streaming feedback: `text_delta` events for progressive output, typing indicators possible
- Timeout handling: `auto_retry_start/end` events, `abort` command

### What Each Component Owns

| Component | Owns | Doesn't Own |
|-----------|------|-------------|
| **PI** | Sessions, transcripts, compaction, tool policies, MCP tools, system prompt, agent loop | Channel I/O format |
| **telegramy** | Telegram Bot API integration, message parsing, validation, retry, WebSocket broadcast, send operations | Agent logic |
| **relay** | RPC client management, Telegram↔RPC translation, chat→session routing | State, sessions, logic |

### Data Flow (Bidirectional via RPC)

```
telegramy WebSocket event
    │  {"message": {"chat": {"id": "123"}, "from": {"first_name": "koena"}, "text": "analyze BTC"}}
    ▼
relay: resolve chat→session, format message
    │  {"type": "prompt", "message": "[from=koena] analyze BTC"}
    ▼
PI RPC stdin
    │  PI processes with full agent loop (tools, compaction, MCP)
    ▼
PI RPC stdout events
    │  {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "BTC is..."}}
    │  {"type": "agent_end", "messages": [...]}
    ▼
relay: extract final response text
    │
    ▼
PI calls telegramy MCP: send_message(chat_id="123", text="...")
    │  (or relay sends via telegramy directly from captured response)
    ▼
User receives reply on Telegram
```

### Why This Works

1. **Structured protocol.** No parsing PI's output. No guessing when PI is done. Events tell the relay exactly what's happening.

2. **PI already has MCP tools** for telegramy (send_message), kapsula (memory search), finbar (trading analysis), and webdown (web content). No new tools needed.

3. **PI already has sessions.** RPC mode supports `--session-dir` for persistent storage, `new_session` command for creating sessions.

4. **PI already has compaction.** RPC exposes `compact` command and `compaction_start/end` events.

5. **PI already has commands.** `/reset`, `/model`, `/compact` work through RPC `prompt` just like in interactive mode. No relay-side command parsing needed.

6. **PI is the single source of truth.** No relay-side state. No dual-write problems.

---

## 5. PI Configuration Design

The relay starts PI with a config directory:

```
config/hal/
├── system.md       # Identity, instructions, Telegram awareness, command handling
├── agents.md       # Developer constitution (shared with all HAL components)
└── mcp.json        # MCP server configuration
```

### system.md — Key Sections

PI's system prompt needs to know:
1. **It's on Telegram** — messages arrive with `[chat=X from=Y]` headers
2. **How to reply** — use telegramy's `send_message(chat_id, text)` MCP tool
3. **Available tools** — kapsula, finbar, webdown, telegramy, filesystem
4. **Command handling** — /reset, /status, /compact (PI handles these, not the relay)
5. **Session isolation** — treat each chat_id independently

### mcp.json — Server Configuration

```json
{
  "servers": {
    "telegramy": {"url": "http://localhost:8001/mcp"},
    "kapsula":   {"url": "http://localhost:8002/mcp"},
    "finbar":    {"url": "http://localhost:8003/mcp"},
    "webdown":   {"url": "http://localhost:8004/mcp"},
    "filesystem": {"type": "builtin"}
  }
}
```

### Session Directory

```
sessions/hal/
├── chat_123456/    # DM with koena
├── chat_789012/    # Another DM
└── chat_-100123/   # Group chat
```

PI's session directories persist on disk. If the relay restarts, PI picks up where it left off.

---

## 6. Commands: Who Handles Them?

Decision: **PI handles commands, not the relay.**

The relay forwards `/reset` like any other message. PI's system prompt instructs it to recognize and handle commands. This keeps the relay thin and lets commands evolve without relay changes.

If a command needs to be fast (no LLM call), PI can handle that internally — it already has fast-path logic for certain directives.

If future needs require relay-level command interception (e.g., `/stop` to kill a runaway session), that can be added as a pre-filter in the relay without changing the overall architecture.

---

## 7. Process Lifecycle

### Startup
```bash
# 1. Start all MCP services
python -m kapsula.presentation.mcp &
python -m finbar.startup.mcp &
python -m webdown.startup.mcp &
python -m telegramy.src.main &

# 2. Start the relay (spawns PI in RPC mode internally)
python -m hal_relay.main
```

The relay spawns PI as a subprocess: `pi --mode rpc --config-dir config/hal --session-dir sessions/hal`

### Supervision
The relay is supervised by the OS (systemd, Docker restart policy, or pm2). If PI crashes, the relay detects the subprocess exit and exits itself. The supervisor restarts. PI resumes from its persisted session directory.

### Shutdown
SIGTERM → relay sends shutdown to PI subprocess → PI exits gracefully → relay exits.

### RPC Client in Python

PI's RPC mode uses strict JSONL framing over stdin/stdout. The relay needs a Python RPC client:

```python
# hal_relay/pi_client.py — minimal RPC client for PI subprocess

class PIClient:
    """Manage a PI subprocess via RPC protocol."""
    
    def __init__(self, config_dir: str, session_dir: str):
        self.proc = None
        self.config_dir = config_dir
        self.session_dir = session_dir
        self._response_handlers: dict[str, asyncio.Future] = {}
        self._event_handlers: list[callable] = []
    
    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            "pi", "--mode", "rpc",
            "--config-dir", self.config_dir,
            "--session-dir", self.session_dir,
            "--no-session",  # sessions managed per-chat
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
    
    async def prompt(self, message: str) -> str:
        """Send a prompt, collect full response via events."""
        cmd = json.dumps({"type": "prompt", "message": message})
        self.proc.stdin.write((cmd + "\n").encode())
        await self.proc.stdin.drain()
        
        # Collect text_delta events until agent_end
        parts = []
        async for line in self._read_lines():
            event = json.loads(line)
            if event.get("type") == "message_update":
                delta = event.get("assistantMessageEvent", {})
                if delta.get("type") == "text_delta":
                    parts.append(delta["delta"])
            elif event.get("type") == "agent_end":
                break
        return "".join(parts)
    
    async def abort(self):
        cmd = json.dumps({"type": "abort"})
        self.proc.stdin.write((cmd + "\n").encode())
        await self.proc.stdin.drain()
    
    async def _read_lines(self):
        """Read JSONL lines from PI stdout."""
        buffer = b""
        while True:
            chunk = await self.proc.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line.endswith(b"\r"):
                    line = line[:-1]
                yield line.decode("utf-8")
```

---

## 8. PI's MCP Support

**Important:** PI does not have built-in MCP support. From PI's philosophy: "No MCP. Build CLI tools with READMEs (see Skills), or build an extension that adds MCP support."

The user has installed an MCP extension for PI (likely a third-party pi package or a custom extension). The relay architecture does not depend on how MCP is implemented — it just needs PI to have the tools available. The MCP extension must be present in PI's config directory.

This is worth noting because it means PI's tool surface is extension-dependent. If the MCP extension breaks or changes, PI loses access to telegramy/kapsula/finbar/webdown tools. The relay should detect this (PI will fail tool calls) and report it.

---

## 9. What We Deliberately Omitted

| Feature | Why Omitted | When to Add |
|---------|------------|-------------|
| Sub-agent spawning | Single-user, single-conversation | When parallel research is needed |
| Multi-channel | Only Telegram | When adding Discord/WhatsApp |
| Streaming/typing indicators | RPC supports text_delta events; add later | When user experience needs it |
| Tool approval gates | Single trusted user; PI extensions handle safety | When sharing HAL with others |
| Auth/profile rotation | Single API key per service | When hitting rate limits |
| Plugin system | Five MCPs, not fifty | When MCP list grows unmanageably |
| Admin dashboard | Overhead for personal use | When debugging needs it |
| Message deduplication | telegramy's update offset handles this | Never (telegramy owns it) |
| Web UI | Terminal + Telegram sufficient | When desired |

---

## 10. Open Questions for Future

1. **Per-chat PI sessions:** Should each Telegram chat map to a separate PI RPC session? The relay could run one PI process per chat (via `--session <file>`), or use one PI process with `new_session`/`switch_session` RPC commands. One process per chat is simpler but uses more resources. One process multiplexing sessions is more complex but efficient.

2. **RPC subprocess management:** If spawning one PI process per chat, the relay needs a pool. How many concurrent PI processes? What's the memory/CPU profile?

3. **Telegram media:** Photos can be forwarded to PI via RPC's `images` field in prompt commands (base64). Voice notes and stickers need pre-processing. Should the relay transcribe voice notes before sending to PI?

4. **Terminal + Telegram simultaneously:** If PI sessions are persisted to disk, a terminal PI session and a relay PI session using the same session file would conflict. Either use different session files, or accept that only one can be active at a time.

5. **Response delivery strategy:** Two options: (a) PI uses telegramy MCP tools to send replies — PI has full control over formatting and timing, or (b) the relay captures PI's final response text and sends it via telegramy — relay controls delivery, PI stays pure. Option (a) is what the user uses today. Option (b) gives the relay more control for chunking, typing indicators, and delivery guarantees.

6. **Kapsula as long-term memory:** Should PI proactively write important facts to kapsula, or should the user explicitly ask? PI's system prompt should define the memory strategy.

7. **Model selection:** PI's RPC mode supports `set_model` command. The relay could map Telegram `/model gpt-5.5` to this RPC command, giving instant model switching without burning tokens.

---

## 10. Key Files Reference

| File | Purpose |
|------|---------|
| `C:/HAL/Github/hal-relay/specs/2026-06-17_hal-relay/01-story.md` | User story, architecture, non-goals |
| `C:/HAL/Github/hal-relay/specs/2026-06-17_hal-relay/02-scenarios.md` | Gherkin scenarios with verify blocks |
| `C:/HAL/Github/hal-relay/specs/2026-06-17_hal-relay/03-domain.md` | Domain model (minimal, stateless) |
| `C:/HAL/Github/hal-relay/specs/2026-06-17_hal-relay/04-implementation.md` | Step-by-step build guide |
| `C:/HAL/Github/openclaw/src/agents/harness/` | Reference: harness abstraction pattern |
| `C:/HAL/Github/openclaw/src/channels/turn/kernel.ts` | Reference: channel turn processing |
| `C:/HAL/Github/telegramy/src/presentation/mcp/` | telegramy MCP server (send tools) |
| `C:/HAL/Github/telegramy/src/infrastructure/adapters/` | telegramy WebSocket + Telegram API |
