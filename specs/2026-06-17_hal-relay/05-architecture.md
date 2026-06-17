# HAL Relay — Architecture Decisions (ADRs)

> Context and rationale for the load-bearing decisions. Each ADR records *what*
> was decided, *why*, and the *consequences*. See `01-story.md` for the overall
> positioning and `04-implementation.md` for how each decision is realized.

---

## ADR-1: Three separate services, not embedded in telegramy

**Context.** telegramy already has WebSocket fan-out, selective subscriptions,
durable delivery, and MCP send tools. It was tempting to put the relay (the PI
binding logic) inside telegramy to reuse that infrastructure in-process.

**Decision.** Keep hal-relay as a separate process. telegramy stays a generic,
agent-agnostic transport hub; the relay is its own service that connects to
telegramy over its published WebSocket + MCP contracts.

**Consequences.**
- (+) telegramy remains reusable across N consumers and survives a PI crash.
- (+) Process isolation: a PI bug can't take down message delivery to others.
- (+) Independent deploy/test cadence for trust policy, routing, presentation.
- (−) One extra localhost WS hop and one extra process — negligible next to an
  LLM call's latency.
- (−) The relay must speak MCP itself to send replies (a small HTTP client,
  mirroring telegramy's own extension).

The reuse argument *for* embedding was already satisfied by the separate
design: the WS subscription **is** the reuse boundary. Moving in-process buys
no additional reuse and costs isolation.

---

## ADR-2: Relay-capture delivery (Option B), not PI-sends

**Context.** When PI answers a prompt, who sends the reply to Telegram? Two
models: (A) PI uses telegramy's `send_message` MCP tool itself; (B) the relay
reads PI's turn to `agent_end`, captures the final assistant text, and sends it
via telegramy MCP.

**Decision.** Option B. The relay owns the outbound leg; chat_id never enters
PI's context.

**Consequences.**
- (+) chat_id stays out of PI's context (no fragility from an LLM dropping it
  after compaction).
- (+) Delivery supervision: the relay knows whether a turn finished and the
  reply was sent — no silent failure if PI crashes or forgets to reply.
- (+) Cleanest layering: relay = presenter, PI = pure agent (per AGENTS.md).
- (+) Approval flows map naturally (relay owns the Telegram keyboard).
- (−) PI's reply is one text blob per turn (no multi-message mid-conversation).
  Acceptable for a chat assistant.
- Upgrade path to Option C (streaming via `send_streaming_text`) is relay-side
  only; no telegramy or PI change.

PI retains telegramy tools in its config (for the optional hybrid media path),
but MVP text replies are relay-sent.

---

## ADR-3: One PI process per chat (cardinality model A)

**Context.** PI in RPC mode is one conversation per process (stdin/stdout,
no network socket, single session). "HAL across N chats" could be: (A) N
processes; (B) one process that switches sessions; (C) an external persistent
HAL service bridging stdio to a socket.

**Decision.** Model A — spawn one PI process per chat, on demand.

**Consequences.**
- (+) True concurrency: chat A's long turn doesn't block chat B.
- (+) Each process fully isolated (own session file, own context, own crash domain).
- (+) Spawned and owned by the relay (PI's stdio-only RPC forces this anyway).
- (−) N processes = more memory. Acceptable for a personal assistant (low chat count).
- (−) "HAL" feels diffuse (many processes), but identity is the *config dir*
  (HAL project dir), shared by all — so it's still one HAL, many conversations.

Model B (single process, session-switch) is simpler but globally serializes
chats; Model C (external service) pays a bridge-tax for stdio→socket with
little functional gain for a single consumer.

---

## ADR-4: HAL profiled via a project directory (not --config-dir)

**Context.** PI has no `--config-dir` flag. Configuration loads from fixed
locations: `~/.pi/agent/` (global) and `<cwd>/.pi/` (project-local). A
"HAL profile" needs its own system prompt, context file, and capabilities
without colliding with the owner's terminal PI.

**Decision.** HAL is a project directory (`hal/`) containing `AGENTS.md`
(context), `.pi/SYSTEM.md` (system prompt), and `.pi/extensions/*.ts` (MCP
tools). The relay spawns PI with `cwd=hal/` and `-a` (trust it).

**Consequences.**
- (+) Idiomatic PI: profiles *are* project dirs.
- (+) Everything HAL-related lives in one inspectable folder.
- (+) Session isolation is orthogonal via `--session <path>` regardless.
- (−) Trust handling required: non-interactive RPC won't prompt, so `-a` or a
  pre-saved trust decision is mandatory (else `.pi/` silently doesn't load).
- Alternative considered: `HOME=<hal-home>` for full isolation (what Docker
  does). Chosen against because the project-dir approach is more transparent
  and the owner runs locally, not containerized, for now.

---

## ADR-5: MCP via TypeScript extensions, not a declarative config

**Context.** PI has no built-in MCP support and no `mcp.json` schema. MCP
integration is provided by TypeScript extensions that connect to each MCP
server, discover its tools, and register them via `pi.registerTool()`. The
telegramy repo ships `.pi/extensions/telegramy.ts` as its integration.

**Decision.** HAL's MCP surface is one extension per service in
`hal/.pi/extensions/` (telegramy, kapsula, finbar, webdown), each copied from
telegramy's reference with only the URL changed.

**Consequences.**
- (+) Proven pattern (telegramy already works this way).
- (+) Each extension is self-contained: connects on `session_start`, discovers
  tools dynamically, converts JSON-schema → TypeBox.
- (+) The relay's own outbound (contract 3) mirrors the same MCP-over-HTTP
  pattern in Python — no `mcp` SDK, just the raw JSON-RPC handshake.
- (−) Duplicated boilerplate across four extensions (acceptable; each is small).
- (−) If an MCP service moves, its extension's URL logic must be updated.

---

## ADR-6: Auto-allow tool-call approval for MVP

**Context.** PI's extensions can emit `extension_ui_request` (select/confirm/
input) mid-turn, which in RPC mode **block until answered**. An unhandled
request deadlocks the turn. The question is whether to route these to the user
(Telegram inline keyboard) or auto-resolve them.

**Decision.** For the MVP, auto-respond to all UI requests permissive
(confirm=true; select/input/editor → empty/default). The handler is built (so
no deadlock); the keyboard-confirm path is deferred.

**Consequences.**
- (+) Simple, no round-trip latency, no inline-keyboard plumbing.
- (+) Defensible because every reachable sender is trusted (allowlisted DM or
  whitelisted group), so "auto-allow" is auto-allow-by-a-trusted-user.
- (−) In an open group, any member can drive tool calls on the owner's
  credentials. Mitigated by the owner controlling group membership and being
  able to disable a group instantly (config change + restart).
- The keyboard-confirm path is designed (the seam exists: callback_query in →
  `extension_ui_response` out) and can be built in a later slice without
  restructuring.

---

## ADR-7: Per-chat serialization via asyncio.Lock, not follow_up/steer

**Context.** PI's RPC spec returns an error if `prompt` is sent while the agent
is streaming (unless `streamingBehavior` is set). Two messages to the same chat
must therefore not overlap.

**Decision.** Per-chat `asyncio.Lock`: the second message waits for the first
turn's `agent_end`, then sends a fresh `prompt`. `follow_up`/`steer` (which
queue *within* a running turn) are deferred.

**Consequences.**
- (+) Simple and correct; no reliance on PI's queueing semantics.
- (+) The WebSocket read loop stays unblocked (per-message `asyncio.create_task`).
- (−) A second message to a busy chat waits for the whole first turn. Acceptable
  for a personal assistant; if a group gets chatty, add `follow_up` queuing.
- (−) Needs a `TURN_TIMEOUT` + `abort` so a runaway or dead PI mid-turn
  doesn't hold the per-chat lock forever. On timeout the relay aborts the
  turn (warm process preserved); if abort itself goes unacked it kills the
  process and the router restarts it. See ADR-8.

---

## ADR-8: Warm per-chat processes; no idle eviction

**Context.** Once a chat has messaged, its PI process holds the full session
in memory. Two patterns were considered: (a) keep every warm process alive
indefinitely; (b) evict idle processes after some timeout and respawn on demand
from the persisted session file.

**Decision.** (a) — keep warm processes alive. Do not speculatively tear them
down for efficiency. A process is torn down only on relay shutdown, on a
verified crash, or when a stuck turn's `abort` escalates to kill.

**Consequences.**
- (+) **Responsiveness.** Every message after the first gets a warm process:
  no multi-second respawn (cold start, extension load, MCP reconnect, session
  read) and no loss of in-memory context. For a real chat this is the difference
  between a snappy assistant and a sluggish one.
- (+) **Simplicity.** No LRU pool, no idle timers, no respawn-on-demand path to
  test. The router is just `dict[chat_id -> AgentClient]`.
- (+) **Correctness.** Session files have a single live writer at all times;
  no risk of a stale evicted process racing a freshly-spawned one on the same file.
- (−) Memory grows with the number of distinct chats ever seen. Each warm
  process holds a session + model config (tens of MB, not GB). For a personal
  assistant (handful of chats) this is negligible.
- Idle eviction is an explicit **non-goal for the MVP.** Revisit only if a
  measurable memory ceiling appears (e.g. dozens of concurrent chats) — and
  even then, prefer evicting on a real signal (memory pressure) over a timer.

The key invariant: **never tear down a healthy warm process just to save
memory.** Warmth is the feature; teardown is only for shutdown/crash/abort.
