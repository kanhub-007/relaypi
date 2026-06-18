# RelayPI — Domain Model

## Overview

The relay has **no business logic**. It is a binding layer that owns trust,
routing, supervision, and presentation between Telegram-land (telegramy) and
agent-land (PI). What state it holds is runtime/policy state, not domain state
— PI remains the single source of truth for sessions, context, compaction, and
tool execution.

### State the relay *does* hold (and why it's not "domain" state)
| State | Kind | Purpose |
|-------|------|---------|
| Allowlist (DM users + open/restricted groups) | policy | Trust gate before any processing |
| chat_id → AgentClient map | runtime | Per-chat PI process routing |
| Per-chat `asyncio.Lock` | runtime | Serialize turns on one PI process |

These are transport/policy plumbing. They are not persisted as domain truth —
the allowlist is a static config; PI's `--session <path>` persists the
conversations the relay only references.

## Entities (transport DTOs)

These are **data crossing boundaries**, not rich domain entities. The relay
deliberately has no behaviour-bearing entities (it has no domain logic to put
in them). They are small frozen dataclasses.

| DTO | Fields | Notes |
|-----|--------|-------|
| `InboundMessage` | `chat_id`, `chat_type`, `sender_user_id`, `sender_username`, `sender_first_name`, `text` | Parsed from a telegramy WS event |
| `FormattedPrompt` | `text` | `[from={username}] {message}` (display-only) |
| `OutboundReply` | `chat_id`, `text` | Final assistant text captured from PI, ready to send |
| `GroupConfig` | `mode` (`open`/`restricted`), `members` (set[int] when restricted) | Allowlist entry |

**chat_id never enters PI's context.** The relay holds it for routing and
sending. The prompt prefix carries `username` (display-only) so HAL can address
group members distinctly in a shared session. Fallback to `first_name`, then
`anonymous`, when `username` is absent.

## Interfaces (ports, for DI)

The relay's ports map one-to-one onto the four contracts plus internal policy.
All are abstract (`ABC`/`Protocol`) in `core/domain/interfaces/`; concrete
implementations live in `infrastructure/` and are wired by `startup/`.

| Interface | Methods | Implemented by | Contract |
|-----------|---------|----------------|----------|
| `MessageSource` | `async events() → AsyncIterator[dict]` | WS subscriber to telegramy | #1 inbound |
| `AgentClient` | `async prompt_and_collect(message) → str`, `async abort() → None`, `is_alive() → bool`, `async stop() → None` | PI RPC subprocess client | #2 control |
| `MessageSender` | `async send_message(chat_id, text) → None`, `async close() → None`, (future) `send_streaming_text(...)` | telegramy MCP client | #3 outbound |
| `Allowlist` | `allows(msg: InboundMessage) → bool` | Static-config allowlist | internal policy |
| `SessionRouter` | `async get_or_create(chat_id) → AgentClient`, `async stop_all() → None` | Per-chat PI process pool | internal routing |

## Data Flow

**Inbound → PI:**
```
MessageSource.events()                       telegramy WS (filtered, contract 1)
    │  raw event dict
    ▼
parse_inbound(event) → InboundMessage | None  (skip non-message / empty text)
    │
    ▼
Allowlist.allows(msg)?  ── no ──► drop silently + log
    │ yes
    ▼
format_prompt(msg) → FormattedPrompt          "[from=koena] analyze BTC"
    │
    ▼
SessionRouter.get_or_create(chat_id)          per-chat PI process (--session <path>)
    │
    ▼
AgentClient.prompt_and_collect(text)          PI RPC stdin (contract 2)
```

**PI → Outbound (Option B):**
```
PI RPC stdout events
    │  response(id) → ack/reject the command
    │  message_update(text_delta…) → streaming (ignored for capture)
    │  tool_execution_*, compaction_*, … → (future: status/indicators)
    │  extension_ui_request → approval round-trip (see below)
    │  agent_end → turn finished
    ▼
AgentClient reads to agent_end, then get_last_assistant_text() → final text
    │
    ▼
MessageSender.send_message(chat_id, text)     telegramy MCP (contract 3)
```

## Approval Round-Trip (seam, even though MVP auto-allows)

This must be designed now even if the MVP auto-responds, because in RPC mode a
dialog request **blocks until answered** — an unhandled request deadlocks the
turn (no `agent_end` ever arrives).

```
PI emits: {"type":"extension_ui_request","id":U,"method":"confirm",...}  → BLOCKS
    │
    ▼
relay reader dispatches to handler
    │  MVP: auto-respond per policy (e.g. confirm=true)
    │  Future: render Telegram inline keyboard → wait for callback_query →
    │          reply with extension_ui_response {id:U, confirmed:bool}
    ▼
relay sends: {"type":"extension_ui_response","id":U,"confirmed":true}    → PI unblocks
```

Fire-and-forget UI methods (`notify`, `setStatus`, `setWidget`, `setTitle`,
`set_editor_text`) emit a request but expect **no** response — they are
displayed or ignored.

## Concurrency Model

- **Per-message `asyncio.create_task`** so the WebSocket read loop is never
  blocked by a long PI turn.
- **Per-chat `asyncio.Lock`** so two messages to the same chat serialize (never
  send `prompt` to a streaming PI — the RPC spec returns an error). The second
  message waits for the first turn's `agent_end`, then sends a fresh `prompt`.
- **Across chats:** fully concurrent (separate PI processes, separate locks).

`follow_up`/`steer` (queue-within-running-turn) are documented future
enhancements, not MVP.

## PI Configuration

PI has **no `--config-dir` flag**. HAL is profiled via a **project directory**
that PI loads from its cwd: `AGENTS.md` (context file), `.pi/SYSTEM.md`
(system prompt), and `.pi/extensions/*.ts` (capabilities). The relay spawns PI
with `cwd=<HAL project dir>`, `-a` (trust it — required in non-interactive RPC
mode, else `.pi/` resources silently don't load), and an explicit per-chat
session file:

```
pi --mode rpc -a --session <sessions/hal/chat_{id}.jsonl>   # cwd = HAL project dir
```

```
hal/                              # the HAL "project dir" (PI profile)
├── AGENTS.md                     # context file (developer constitution)
├── .pi/
│   ├── SYSTEM.md                 # HAL system prompt
│   └── extensions/
│       ├── telegramy.ts          # MCP bridge (copy from telegramy repo)
│       ├── kapsula.ts            # same pattern, different URL
│       ├── finbar.ts             # same pattern, different URL
│       └── webdown.ts            # same pattern, different URL
└── sessions/
    ├── chat_123456.jsonl         # one persisted conversation per chat (PI-owned)
    └── chat_g100111000.jsonl     # group (negative id → 'g' prefix)
```

**There is no `mcp.json`.** PI's MCP integration is via TypeScript extensions
in `.pi/extensions/`, each of which connects to its MCP server over
streamable-http, discovers tools via `tools/list`, and registers them via
`pi.registerTool()`. telegramy's `.pi/extensions/telegramy.ts` is the reference
implementation — copy it for the others, changing only the URL/port.

**telegramy stays configured in PI** (its extension is present) even though MVP
text replies are sent by the relay (not PI). This preserves the hybrid upgrade
path: PI can later proactively send media/files via telegramy tools. chat_id
would enter PI's context only in that media case — acceptable, and opt-in.

The relay itself is profile-agnostic — it points PI at the project dir (cwd)
and the per-chat session file, nothing more.
