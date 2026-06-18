# relaypi

The binding layer between **telegramy** (Telegram transport) and **PI** (the HAL agent).
A thin, focused service that turns Telegram messages into PI RPC prompts and
delivers PI's replies back — nothing more. PI owns all the brainpower
(sessions, context, compaction, tools); telegramy owns all the Telegram plumbing;
the relay is the seam between them.

## Where it fits

```
                        ┌─────────────────────────────────┐
                        │          telegramy               │  ← generic transport hub
   Telegram ◄═══════════│  Bot API / polling / webhook     │
   Bot API  ═══════════►│  WS fan-out (selective subs) ────┼──┐ inbound  (contract 1)
                        │  send surface (MCP tools) ◄──────┼──┤ outbound (contract 3)
                        └──────────────────────────────────┘  │
                 ┌────────────────────────────────────────────┘
                 ▼                                            ┌──────────────┐
        ╔════════════════════════════════════════╗  RPC ▼    │   PI (HAL)   │
        ║              relaypi                  ║ stdin ──►│  (cognition) │
        ║  • allowlist (DMs + open/restricted)   ║ stdout ◄─│  sessions    │
        ║  • chat_id → PI session routing        ║ (contr 2)│  compaction  │
        ║  • prompt formatting                   ║          │  tool loop   │
        ║  • PI process lifecycle / supervision   ║          │  kapsula/... │
        ║  • presenter: PI reply → Telegram msg   ║          └──────────────┘
        ╚════════════════════════════════════════╝
```

**Four contracts, all pre-existing** — the relay depends on telegramy and PI only
through their published surfaces:

| # | Contract | Mechanism | Direction |
|---|---|---|---|
| 1 | Inbound events | telegramy WS `subscribe` | telegramy → relay |
| 2 | Agent control | PI RPC over stdin/stdout | relay → PI |
| 3 | Outbound send | telegramy MCP tools (`send_message`) | relay → telegramy |

No new telegramy endpoint required. See [`docs/architecture.md`](docs/architecture.md)
for the full design (and `specs/` for the spec-driven detail).

---

## Setup

### Prerequisites

Before you start, these must be running:

| Service | Purpose | Default address |
|---------|---------|----------------|
| **telegramy** (WS + MCP) | Inbound events + outbound send | `ws://localhost:8765` / `http://localhost:8005/mcp` |
| **PI** (`pi`) | Agent cognition (global npm: `npm i -g @anthropic/pi`) | spawned as subprocess |
| **MCP tools** (optional) | kapsula (memory), finbar (trading), webdown (web) | localhost:8002-8004 |

Verify each:
```bash
# PI installed?
pi --version

# telegramy reachable? (WebSocket)
curl http://localhost:8765   # should return a WebSocket upgrade response

# telegramy MCP reachable?
curl http://localhost:8005/mcp
```

### 1. Install relaypi

```bash
cd relaypi
pip install -e ".[dev]"
```

### 2. Configure the HAL project dir

PI has no `--config-dir` flag — a "profile" is a project directory loaded from
`cwd`. The relay spawns PI with `cwd=hal/` and `-a` (trust).

```bash
# One-time: set up the HAL project dir
# See hal/README.md for full instructions
cp C:\HAL\AGENTS.md hal/AGENTS.md
cp C:\HAL\Github\telegramy\.pi\extensions\telegramy.ts hal/.pi/extensions/

# (Create kapsula.ts, finbar.ts, webdown.ts the same way)

# Verify the profile loads
cd hal && pi -a --print "hello"
cd ..
```

If the extensions connect, you'll see `notify` messages like
"telegramy: Connected, N tools discovered".

### 3. Configure the allowlist

The allowlist determines **who can talk to HAL**. Without it, the relay starts
but silently drops every message (fail-closed).

```bash
# Copy the example
cp config/allowlist.yaml.example config/allowlist.yaml

# Edit — add your Telegram user ID(s)
#   DM users: anyone who can DM HAL directly
#   Groups: open (any member) or restricted (only listed members)
$EDITOR config/allowlist.yaml
```

To find your Telegram user ID: message [@userinfobot](https://t.me/userinfobot).

Example:
```yaml
dm_users:
  - 987654321         # your Telegram user ID

groups:
  - id: -100111000    # group chat (negative id)
    mode: open         # any member may use HAL
```

See [`docs/configuration.md`](docs/configuration.md) for full gate rules.

### 4. Run

```bash
python -m relaypi.main
```

The relay connects to telegramy's WebSocket, subscribes to message events, and
waits. Send a message to your bot on Telegram — HAL should reply.

Stop with **Ctrl+C** (Windows / POSIX). The relay waits for in-flight turns,
stops all PI subprocesses (bounded, then killed), and exits cleanly.

---

## Environment variables

All optional — defaults target a local single-host setup.

| Var | Default | Purpose |
|-----|---------|---------|
| `RELAYPI_WS_URL` | `ws://localhost:8765` | telegramy WebSocket |
| `RELAYPI_MCP_URL` | `http://localhost:8005/mcp` | telegramy MCP send endpoint |
| `RELAYPI_PI_BIN` | `shutil.which("pi")` | PI executable path (Windows: resolves the `.cmd` shim) |
| `RELAYPI_PROJECT_DIR` | `hal` | HAL project dir (AGENTS.md + .pi/) |
| `RELAYPI_SESSION_DIR` | `hal/sessions` | per-chat `.jsonl` root |
| `RELAYPI_ALLOWLIST` | `<repo>/config/allowlist.yaml` | allowlist config file (resolved from package path, not cwd) |

**Windows:** the relay is developed and tested on Windows. Shutdown is driven by
`KeyboardInterrupt` (Ctrl+C / console close) because `loop.add_signal_handler`
is unsupported there. `pi` is resolved via `shutil.which` so the npm-installed
`pi.cmd` shim is found without `shell=True`.

---

## Development

```bash
pytest                 # 66 tests, classical school (fakes, outcome assertions)
ruff check relaypi tests && black --check relaypi tests
```

See [`docs/development.md`](docs/development.md) — especially the **five PI RPC
protocol traps** that are the most likely source of future bugs.

---

## License

MIT
