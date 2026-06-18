# Configuration

## Allowlist (`config/allowlist.yaml`)

Static — edit and restart the relay to change it. Determines who can talk to HAL.

```yaml
dm_users:                       # Telegram user IDs allowed to DM HAL
  - 987654321

groups:                         # Group chats HAL may operate in (ids are negative)
  - id: -100111000              # open group: any member may use HAL
    mode: open

  - id: -100222000              # restricted group: only listed members may use HAL
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

To find your Telegram user id: message [@userinfobot](https://t.me/userinfobot).

## HAL project dir (`hal/`)

PI's profile. See `hal/README.md` for one-time setup:
1. Copy `AGENTS.md` from `C:\HAL\AGENTS.md`.
2. Copy telegramy's `.pi/extensions/telegramy.ts` into `hal/.pi/extensions/`.
3. Derive kapsula/finbar/webdown extensions by duplicating it (change the URL/port only).

## Session storage (`hal/sessions/`)

Per-chat `.jsonl` files, created and owned by PI. Examples:
- `chat_123456.jsonl` — a DM
- `chat_g100111000.jsonl` — a group (negative id → `g` prefix)

The relay computes the path; it does not read or write these files. They persist
across relay restarts, so HAL resumes each conversation where it left off.

## Environment variables

See the table in the root `README.md`. All optional; defaults target a local
single-host setup.
