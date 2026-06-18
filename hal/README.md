# PI profile directory

This is your PI agent's "profile" — loaded because the relay spawns PI with
`cwd=<this dir>` and `-a` (trust it). PI has no `--config-dir` flag; a profile
IS a project directory. The default name is `hal/` but you can rename it —
just set `RELAYPI_PROJECT_DIR`.

## Layout

```
hal/                              # your PI profile directory
├── AGENTS.md                     # developer constitution (defines how PI works)
├── .pi/
│   ├── SYSTEM.md                 # your agent's system prompt (identity + instructions)
│   └── extensions/
│       ├── telegramy.ts           # MCP bridge — copy from telegramy repo
│       ├── kapsula.ts             # same pattern, different URL (memory)
│       ├── finbar.ts              # same pattern, different URL (trading)
│       └── webdown.ts             # same pattern, different URL (web)
└── sessions/                      # per-chat .jsonl (created at runtime by PI)
```

## One-time setup

### 1. Copy the developer constitution

```bash
cp /path/to/your/AGENTS.md hal/AGENTS.md
```

This file defines coding conventions, architecture rules, and patterns PI follows.

### 2. Copy the telegramy extension

```bash
cp /path/to/telegramy/.pi/extensions/telegramy.ts hal/.pi/extensions/
```

This gives your agent access to `send_message`, `send_audio`, `send_photo`,
`send_file` — needed for replies with media.

### 3. Create extensions for other MCP services

Duplicate `telegramy.ts` and change only the MCP URL resolution — env var name
and default port:

| Service | Env var prefix | Default port |
|---------|---------------|-------------|
| kapsula (memory) | `KAPSULA_MCP_` | 8002 |
| finbar (trading) | `FINBAR_MCP_` | 8003 |
| webdown (web) | `WEBDOWN_MCP_` | 8004 |

Each extension follows the same pattern: on `session_start`, connect to its MCP
server over streamable-http, discover tools via `tools/list`, register each via
`pi.registerTool()`.

### 4. Customize the system prompt

Edit `.pi/SYSTEM.md` to describe your agent's identity, available tools, and
behavior. The prompt should mention the `[chat=...]` prefix (added by the relay)
so your agent knows it can call telegramy media tools.

## Trust

`-a` is passed on every spawn (required because RPC mode is non-interactive
and won't show a trust prompt — without it, `.pi/` resources silently don't
load). Alternatively, pre-trust the dir once via an interactive `pi` session
here, which saves the decision.

## Verify the profile loads

```bash
cd hal
pi -a --print "hello"
```

If extensions connect you'll see their `notify` messages
("telegramy: Connected, N tools discovered"). If not, the MCP services aren't
running.

## Session storage

Each Telegram chat gets one persisted session file under `hal/sessions/`
(e.g. `chat_123.jsonl` for a DM, `chat_g100111000.jsonl` for a group). The relay
computes the path; PI owns the contents (history, compaction, persistence).
