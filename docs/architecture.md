# Architecture

> Condensed from `specs/2026-06-17_relaypi/`. See `01-story.md`,
> `03-domain.md`, and `05-architecture.md` there for the full reasoning.

## Three services, three responsibilities

| Service | Owns | Doesn't own |
|---------|------|-------------|
| **telegramy** | Bot API, polling/webhook, rate limits, markdown escaping, retry, selective WS fan-out, MCP send tools | Agent logic |
| **PI (HAL)** | Sessions, transcripts, compaction, tool policies, MCP tools, the agent loop, reasoning | Channel I/O |
| **relaypi** | Allowlist (trust), chat→session routing, prompt formatting, PI process supervision, presentation (PI reply → Telegram message) | Sessions, context, business logic |

Each is valid as a separate service: telegramy is reusable across N consumers;
PI stays channel-pure; the relay is the anti-corruption layer whose process
isolation contains crashes and whose independent deploy lets trust/routing/
presentation evolve on their own cadence. See `05-architecture.md` ADR-1 for
why the relay is **not** embedded in telegramy.

## Delivery model (Option B)

The relay is **not** inbound-only. It reads PI's turn to completion, captures
the final assistant text, and sends the reply via telegramy's MCP. **chat_id
never enters PI's context** — the relay holds it for routing and sending. This
gives clean layering (relay = presenter) and delivery supervision (the relay
always knows whether a turn finished and the reply went out).

Upgrade path to streaming (Option C): adopt telegramy's `send_streaming_text`
on the relay side only. No telegramy or PI change.

## Session model

Each Telegram chat gets **one persistent session file** (`hal/sessions/chat_{id}.jsonl`),
owned entirely by PI — loads on start, appends as the conversation grows,
compacts when the context window fills, persists continuously.

- **Path is a pure function of chat_id** (group ids sanitized: `-100…` → `chat_g100….jsonl`).
  The relay stores no session database.
- **Process lifecycle is decoupled from session lifecycle.** A crashed/restarted
  PI resumes the same file — full context intact.
- **One owner per file at a time.** Never point two live PI processes at the
  same path.
- **The `--session <path>` flag is load-bearing.** `--no-session` would discard
  exactly the history and compaction that make PI useful.

## Per-chat processes; no idle eviction

One PI process per chat, kept **warm** across turns (no per-message respawn).
A process is torn down only on relay shutdown, verified crash, or when a stuck
turn's `abort` escalates to kill. Warmth is the feature — see ADR-8. Never tear
down a healthy warm process speculatively.

## HAL profile

PI has no `--config-dir` flag. HAL is profiled via a **project directory**
(`hal/`) that PI loads from its cwd: `AGENTS.md` (context), `.pi/SYSTEM.md`
(system prompt), `.pi/extensions/*.ts` (MCP tools). The relay spawns PI with
`cwd=hal/` and `-a` (trust). See ADR-4 and `hal/README.md`.
