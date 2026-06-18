# hal-relay

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
        ║              hal-relay                  ║ stdin ──►│  (cognition) │
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

## Quickstart

**Prerequisites:** telegramy running (WS + MCP), PI installed globally
(`pi --version`), and any MCP services HAL should use (kapsula/finbar/webdown)
running.

```bash
# 1. Install (editable, with dev tools)
pip install -e ".[dev]"

# 2. Configure trust — copy the example and edit in your Telegram user id
cp config/allowlist.yaml.example config/allowlist.yaml
$EDITOR config/allowlist.yaml

# 3. One-time: set up the HAL project dir (PI profile)
#    See hal/README.md — copy AGENTS.md, copy telegramy's .pi extension, etc.
cd hal && pi -a --print "hello"   # sanity-check the profile loads
cd ..

# 4. Run
python -m hal_relay.main
```

Environment variables (all optional — defaults shown):

| Var | Default | Purpose |
|-----|---------|---------|
| `HAL_RELAY_WS_URL` | `ws://localhost:8765` | telegramy WebSocket |
| `HAL_RELAY_MCP_URL` | `http://localhost:8005/mcp` | telegramy MCP send endpoint |
| `HAL_PI_BIN` | `shutil.which("pi")` | PI executable (Windows: resolves the `.cmd` shim) |
| `HAL_PROJECT_DIR` | `hal` | HAL project dir (AGENTS.md + .pi/) |
| `HAL_SESSION_DIR` | `hal/sessions` | per-chat `.jsonl` root |
| `HAL_ALLOWLIST` | `config/allowlist.yaml` | allowlist config file |

**Windows:** the relay is developed and tested on Windows. Shutdown is driven by
`KeyboardInterrupt` (Ctrl+C / console close) because `loop.add_signal_handler`
is unsupported there. `pi` is resolved via `shutil.which` so the npm-installed
`pi.cmd` shim is found without `shell=True`.

## Development

```bash
pytest                 # 50 tests, classical school (fakes, outcome assertions)
ruff check hal_relay tests && black --check hal_relay tests
```

See [`docs/development.md`](docs/development.md) — especially the **four PI RPC
protocol traps** that are the most likely source of future bugs.

## License

MIT
