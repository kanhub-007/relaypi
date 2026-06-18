# HAL project directory

This is PI's "profile" for HAL — loaded because the relay spawns PI with
`cwd=hal/` and `-a` (trust it). PI has no `--config-dir` flag; a profile IS a
project directory.

## Layout

```
hal/
├── AGENTS.md           # context file (developer constitution) — copy from C:\HAL\AGENTS.md
├── .pi/
│   ├── SYSTEM.md       # HAL system prompt (present)
│   └── extensions/
│       ├── telegramy.ts  # MCP bridge — copy from telegramy repo
│       ├── kapsula.ts    # same pattern, different URL
│       ├── finbar.ts     # same pattern, different URL
│       └── webdown.ts    # same pattern, different URL
└── sessions/            # per-chat .jsonl (created at runtime by PI)
```

## One-time setup

1. Copy the constitution:
   `cp C:\HAL\AGENTS.md hal/AGENTS.md`

2. Copy telegramy's extension (the reference implementation):
   `cp C:\HAL\Github\telegramy\.pi\extensions\telegramy.ts hal/.pi/extensions/`

3. Create the other three extensions by duplicating `telegramy.ts` and changing
   only the MCP URL resolution — env var name and default port:
   - **kapsula**: `KAPSULA_MCP_URL` / `KAPSULA_MCP_HOST` / `KAPSULA_MCP_PORT` (default 8002)
   - **finbar**: `FINBAR_MCP_URL` / `FINBAR_MCP_HOST` / `FINBAR_MCP_PORT` (default 8003)
   - **webdown**: `WEBDOWN_MCP_URL` / `WEBDOWN_MCP_HOST` / `WEBDOWN_MCP_PORT` (default 8004)

   Each extension follows the identical proven pattern: on `session_start`,
   connect to its MCP server over streamable-http, discover tools via
   `tools/list`, register each via `pi.registerTool()`.

## Trust

`-a` is passed on every spawn (required because RPC mode is non-interactive
and won't show a trust prompt — without it, `.pi/` resources silently don't
load). Alternatively, pre-trust the dir once via an interactive `pi` session
here, which saves the decision.

## Verify the profile loads

```
cd hal
pi -a --print "hello"
```

If the extensions connect you'll see their `notify` messages ("telegramy:
Connected, N tools discovered"). If not, the MCP services aren't running.

## Note on sessions

Each Telegram chat gets one persisted session file under `hal/sessions/`
(e.g. `chat_123.jsonl`, `chat_g100111000.jsonl` for a group). The relay
computes the path; PI owns the contents (history, compaction, persistence).
