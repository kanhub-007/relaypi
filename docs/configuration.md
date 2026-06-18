# Configuration

## Allowlist (`config/allowlist.yaml`)

Static — edit and restart the relay to change it. Determines who can talk to
your agent.

```yaml
dm_users:                       # Telegram user IDs allowed to DM the agent
  - 987654321

groups:                         # Group chats the agent may operate in (ids are negative)
  - id: -100111000              # open group: any member may use the agent
    mode: open

  - id: -100222000              # restricted group: only listed members may use the agent
    mode: restricted
    members:
      - 987654321
      - 111222333
```

Gate rules (all evaluated relay-side, before any prompt is sent):
- **DM** (`chat_type == private`): allowed iff `sender_user_id ∈ dm_users`.
- **Group, open**: any member of a whitelisted venue.
- **Group, restricted**: only listed `members`.
- **Anything else** (unknown group, channel post, etc.): dropped silently (fail closed).

Rejected messages are logged, never echoed back (no existence confirmation).
Key on `user.id` (stable, numeric) — usernames are mutable and non-unique.

To find your Telegram user ID: message [@userinfobot](https://t.me/userinfobot).

## PI profile directory (`hal/` by default)

Your agent's identity and capabilities. See `hal/README.md` for setup:
1. Copy your `AGENTS.md` (developer constitution).
2. Copy telegramy's `.pi/extensions/telegramy.ts`.
3. Derive other MCP extensions by duplicating it (change the URL/port only).
4. Customize `.pi/SYSTEM.md` with your agent's identity.

## Session storage (`hal/sessions/`)

Per-chat `.jsonl` files, created and owned by PI. Examples:
- `chat_123.jsonl` — a DM
- `chat_g100111000.jsonl` — a group (negative id → `g` prefix)

The relay computes the path; it does not read or write these files. They persist
across relay restarts, so your agent resumes each conversation where it left off.

## Environment variables

See the table in the root `README.md`. All optional; defaults target a local
single-host setup. Key ones:

| Var | What it does |
|-----|-------------|
| `RELAYPI_PROJECT_DIR` | Rename the profile directory from `hal` to anything |
| `RELAYPI_LOG_LEVEL` | Set to `DEBUG` to see PI events in real-time |
| `RELAYPI_PI_BIN` | Override the PI executable path |
