# relaypi

The binding layer between **telegramy** (Telegram transport) and **PI** (your AI agent).
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
        ╔════════════════════════════════════════╗  RPC ▼    │   PI (agent) │
        ║              relaypi                  ║ stdin ──►│  (cognition) │
        ║  • allowlist (DMs + open/restricted)   ║ stdout ◄─│  sessions    │
        ║  • chat_id → PI session routing        ║ (contr 2)│  compaction  │
        ║  • prompt formatting                   ║          │  tool loop   │
        ║  • PI process lifecycle / supervision   ║          │  extensions  │
        ║  • presenter: PI reply → Telegram msg   ║          └──────────────┘
        ╚════════════════════════════════════════╝
```

**Three contracts, all pre-existing** — the relay depends on telegramy and PI only
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
| **MCP tools** (optional) | Your agent's MCP services | localhost:8002-8004 |

Verify each:
```bash
# PI installed?
pi --version

# telegramy reachable?
curl http://localhost:8765   # should return an HTTP 426 (WebSocket upgrade)
```

### 1. Install relaypi

```bash
cd relaypi
pip install -e ".[dev]"
```

### 2. Configure your PI profile

PI loads its identity from a **project directory** (cwd). The relay spawns PI
with `cwd=<project_dir>` and `-a` (trust). The default directory is `hal/` but
you can rename it — just set `RELAYPI_PROJECT_DIR`.

```bash
# Copy the developer constitution (AGENTS.md)
cp /path/to/your/AGENTS.md hal/AGENTS.md

# Copy telegramy's PI extension (MCP bridge for media sends)
cp /path/to/telegramy/.pi/extensions/telegramy.ts hal/.pi/extensions/

# Create extensions for other MCP services the same way

# Edit the system prompt to describe your agent
$EDITOR hal/.pi/SYSTEM.md

# Verify the profile loads
cd hal && pi -a --print "hello"
cd ..
```

See [`hal/README.md`](hal/README.md) for full profile setup.

### 3. Configure the allowlist

The allowlist determines **who can talk to your agent**. Without it, the relay
starts but silently drops every message (fail-closed).

```bash
cp config/allowlist.yaml.example config/allowlist.yaml
$EDITOR config/allowlist.yaml
```

To find your Telegram user ID: message [@userinfobot](https://t.me/userinfobot).

Example:
```yaml
dm_users:
  - 987654321         # your Telegram user ID

groups:
  - id: -100111000    # group chat (negative id)
    mode: open         # any member may use the agent
```

See [`docs/configuration.md`](docs/configuration.md) for full gate rules.

### 4. Run

```bash
start.bat              # Windows
# or
python -m relaypi.main
```

The relay connects to telegramy's WebSocket, subscribes to message events, and
waits. Send a message to your bot on Telegram — your agent should reply.

Stop with **Ctrl+C**. The relay waits for in-flight turns, stops all PI
subprocesses, and exits cleanly.

---

## Environment variables

All optional — defaults target a local single-host setup.

| Var | Default | Purpose |
|-----|---------|---------|
| `RELAYPI_WS_URL` | `ws://localhost:8765` | telegramy WebSocket |
| `RELAYPI_MCP_URL` | `http://localhost:8005/mcp` | telegramy MCP send endpoint |
| `RELAYPI_PI_BIN` | `shutil.which("pi")` | PI executable path |
| `RELAYPI_PROJECT_DIR` | `hal` | PI profile directory (AGENTS.md + .pi/) |
| `RELAYPI_SESSION_DIR` | `hal/sessions` | per-chat `.jsonl` root |
| `RELAYPI_ALLOWLIST` | `<repo>/config/allowlist.yaml` | allowlist config file |
| `RELAYPI_LOG_LEVEL` | `INFO` | Set to `DEBUG` to see PI events in real-time |

---

## Development

```bash
pytest                 # 68 tests, classical school (fakes, outcome assertions)
ruff check relaypi tests && black --check relaypi tests
```

See [`docs/development.md`](docs/development.md) — especially the **five PI RPC
protocol traps** that are the most likely source of future bugs.

---

## License

MIT
