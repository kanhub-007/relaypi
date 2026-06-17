# HAL Relay — Telegram ↔ PI Bridge

## User Story
As HAL's owner, I want to interact with PI through Telegram with a chat-style
experience (request/response, with HAL's full tool surface), so that HAL is
accessible from anywhere without duplicating PI's capabilities.

## Context

HAL is an ecosystem of independent services. PI is the agent; telegramy is a
generic Telegram bridge; kapsula/finbar/webdown are MCP tools PI can call. The
gap was always the same: no path for `Telegram message → PI receives it →
PI responds → Telegram`.

PI exposes a full RPC protocol (`pi --mode rpc`): structured JSON commands on
stdin, streaming events on stdout, plus an extension-UI sub-protocol for
approval flows. telegramy exposes inbound events over a filtered WebSocket
(selective subscriptions) and outbound send operations as MCP tools. **Every
contract the relay needs already exists** — the relay is pure binding.

## Where the Relay Fits

Three services, three responsibilities. Each earns its existence independently:

- **telegramy** — *Telegram transport.* Bot API, polling/webhook, rate limits,
  markdown escaping, retry, durable delivery, selective WS fan-out, send tools.
  Agent-agnostic and reusable across N consumers.
- **PI (HAL)** — *Agent cognition.* Sessions, context, compaction, tool loop,
  reasoning, MCP tools. Channel-agnostic.
- **hal-relay** — *The binding layer.* The only component that knows both
  "these Telegram chats belong to HAL" and "this is how you drive HAL." Owns
  trust, routing, supervision, and presentation.

```
                        ┌─────────────────────────────────┐
                        │          telegramy               │  ← generic transport hub
                        │  (agent-agnostic, reusable)      │
   Telegram ◄═══════════│  Bot API / polling / webhook     │
   Bot API  ═══════════►│  parse · validate · retry        │
                        │  durable event store · cursor    │
                        │  WS fan-out (selective subs) ────┼──┐ inbound  (contract 1)
                        │  send surface (MCP tools) ◄──────┼──┤ outbound (contract 3)
                        └──────────────────────────────────┘  │
                                                              │ published contracts
                 ┌────────────────────────────────────────────┘
                 │                                            ┌──────────────┐
                 ▼ inbound (WS)                  outbound ►│              │
        ╔════════════════════════════════════════╗  RPC ▼    │   PI (HAL)   │
        ║              hal-relay                  ║ stdin ──►│  (cognition) │
        ║  (binding · trust · supervision)       ║ stdout ◄─│              │
        ║                                        ║          │  sessions    │
        ║  • allowlist (DMs + open/restricted)   ║          │  context     │
        ║  • chat_id → PI session routing        ║ (contr 2)│  compaction  │
        ║  • prompt formatting                   ║          │  tool loop   │
        ║  • PI process lifecycle / supervision   ║          │   kapsula    │
        ║  • presenter: PI reply → Telegram msg   ║          │   finbar     │
        ║  • approval round-trip (auto for MVP)   ║          │   webdown    │
        ╚════════════════════════════════════════╝          │   bash       │
                                                            └──────────────┘
```

### The four contracts (these are the architecture)

Dependency inversion at the process boundary. telegramy depends on nothing
about agents; PI depends on nothing about channels; the relay depends on both,
but only through their published contracts.

| # | Contract | Mechanism | Direction | Status |
|---|---|---|---|---|
| 1 | Inbound events | telegramy WS `subscribe` (chats + events filter) | telegramy → relay | exists |
| 2 | Agent control | PI RPC, JSONL over stdin/stdout (`prompt`, `abort`, `new_session`, `set_model` …) | relay → PI | exists (PI native) |
| 3 | Outbound send | telegramy MCP tools (`send_message`, `send_streaming_text`, …) | relay → telegramy | exists |
| 4 | Agent media (optional/hybrid) | PI → telegramy MCP tools | PI → telegramy | same surface as #3 |

No new telegramy endpoint is required for the MVP.

### Why three services, not one

- **telegramy** would be valuable if HAL didn't exist (it already serves other
  consumers); its cost is amortized, and a PI crash can't interrupt delivery
  to anyone else.
- **PI** must stay channel-pure to remain reusable in terminals, IDEs, CI.
- **hal-relay** is the anti-corruption layer between Telegram-land and
  agent-land. Process isolation contains crashes; independent deploy/test lets
  trust policy, routing, and presentation evolve on their own cadence.

## Architecture: delivery model (Option B)

The relay is **not** inbound-only. It closes the loop itself: it reads PI's
turn to completion, captures the final assistant text, and sends the reply via
telegramy's MCP. **chat_id never enters PI's context** — the relay holds it for
both routing and sending. This is the cleanest layering (relay = presenter) and
gives delivery supervision (the relay always knows whether a turn finished and
the reply went out).

Upgrade path to streaming (Option C): adopt telegramy's `send_streaming_text`
on the relay side only — progressive text via message edits. No telegramy or PI
change needed.

## Session model (why history survives restarts)

Each Telegram chat gets **one persistent session file**, and PI owns it
entirely — loads it on start, appends as the conversation grows, compacts when
the context window fills, and persists continuously. Nothing is ever a blank
slate unless the user explicitly resets.

- **Keyed on `chat_id`**, not user. A DM → one private thread; a group → one
  shared conversation (members build on each other's turns, by design).
- **Path is a pure function of chat_id**: `hal/sessions/chat_{id}.jsonl` (group ids,
  which are negative, are sanitized to `chat_g{id}.jsonl`). The relay computes
  the path; it stores no session database, registry, or map file. (A previous
  draft's `chat_sessions.json` map was removed as redundant and broken.)
- **Process lifecycle is decoupled from session lifecycle.** The PI process is
  just the live reader/writer of a session file. If it dies and restarts, it
  resumes the same file — full context intact. This is why "HAL survives a
  restart" is free, not built.
- **One owner per file at a time.** Two PI processes writing the same session
  file corrupt it. Terminal-HAL and relay-HAL coexist fine using *different*
  session files; never point two live processes at the same path.
- **The load-bearing flag is `--session <path>`** (not `--no-session`, which
  would throw away exactly the history and compaction that make PI useful).

PI remains the single source of truth for session contents; the relay's only
"session management" is the deterministic chat_id → path mapping.

## Non-Goals
- Multi-channel support (Telegram only)
- Streaming/typing indicators for MVP (upgradeable via Option C later)
- Per-user rate limiting (add when a group turns out noisy)
- Relay-side command interception for MVP (`/reset` etc. forwarded as prompts;
  instant `new_session`/`set_model` mapping is a documented future enhancement)
- Admin UI / dashboard
- Tool-call approval via Telegram keyboard for MVP (designed, not built;
  MVP auto-allows — see 02-scenarios.md)
- Session-content state on the relay side (PI owns persistence and compaction;
  the relay holds only a deterministic chat_id → file-path mapping)
