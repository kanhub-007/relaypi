# Development

## Testing — Classical (Detroit) school

```bash
pytest                  # 50 tests
```

Principles (see root `AGENTS.md` §3):
- **Fakes over mocks.** `tests/fakes/` has real, in-memory implementations
  (`FakeAgentClient`, `FakeMessageSource`, `FakeRouter`, `FakeMessageSender`,
  `FakeStreamTransport`). `FakeStreamTransport` is a demand-driven PI simulator
  with genuine protocol behaviour, not a recorder.
- **Outcome assertions, not interactions.** No `assert_called` / `verify`.
- **Real external boundaries** for integration tests: `test_subprocess_stream_transport.py`
  spawns real Python subprocesses; `test_factory.py` runs a real local WebSocket
  server; `test_telegramy_mcp_sender.py` uses httpx's `MockTransport` (a library
  transport seam giving real HTTP semantics without a network).

Concurrency and crash tests use explicit `asyncio.Future` handoffs, not sleeps,
so they're deterministic (stress-verified during development).

## Lint / format / typecheck

```bash
ruff check relaypi tests --fix
black relaypi tests
mypy relaypi            # optional; not yet wired into CI
```

## Architecture & layering

Clean Architecture, Python flavor. Dependencies flow inward:
- `core/domain/` — entities (transport DTOs) + interfaces (ports). Imports nothing internal.
- `core/application/` — `Relay`, `parse`, `format_prompt`. Imports domain only.
- `infrastructure/` — adapters + `ConfigAllowlist` + `PerChatSessionRouter`.
- `startup/factory.py` — the only place that knows concrete adapter classes.

Verified by grep in CI: domain never imports application/infrastructure;
application never imports infrastructure.

---

## ⚠️ The four PI RPC protocol traps

The single most likely source of future bugs. Lifted from `PIRpcClient`
implementation notes; all four are honoured by the current code.

### 1. LF-only framing

PI's RPC mode is strict JSONL with `\n` as the **only** record delimiter.
Do not use generic line readers (e.g. Node's `readline`, or anything that
splits on `U+2028`/`U+2029`) — those are valid inside JSON strings and will
corrupt frames. Split on `\n` only; strip a single trailing `\r`.

### 2. Await `response` before `agent_end`

Every command returns a `{"type":"response","id":N,"success":…}`. A **rejected**
prompt never emits `agent_end`. If you wait for `agent_end` without first
awaiting the `response`, a rejection hangs forever. Always: send command with
`id` → await the matching `response` → only then stream events to `agent_end`.

### 3. Never ignore `extension_ui_request`

In RPC mode, dialog requests (`select`/`confirm`/`input`/`editor`) **block PI
until answered**. An unhandled `extension_ui_request` deadlocks the turn — no
`agent_end` ever arrives. The MVP auto-answers them permissively
(`confirm=true`, others → empty value); fire-and-forget methods (`notify`,
`setStatus`, …) need no reply.

### 4. Explicit `--session <path>` for isolation

Using `--session-dir <dir>` alone makes every spawned PI resume the **same**
most-recent session file in that dir — no isolation between chats, and they'd
corrupt each other. Always pass `--session <path>` with a chat-specific path.

---

## A fifth trap, found during this build

### 5. Arm the event queue *before* sending the command

`agent_end` (and other events) can arrive in the gap between "the `response`
future resolved" and "we start listening on the event queue". If you set the
queue after awaiting the response, that event is dropped and the turn hangs.
Pattern: create the queue, *then* send, *then* await response, *then* read
events — all inside one `try`/`finally` that clears the queue.
