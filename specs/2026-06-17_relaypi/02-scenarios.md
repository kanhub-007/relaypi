# RelayPI — Scenarios

Ordered by MoSCoW priority, then slice. Each scenario shows Gherkin, I/O, and a
Classical-school black-box Verify block using in-memory fakes (no mocks of
internals; assert on outcomes).

Fakes used throughout:
```python
# tests/fakes/
class FakeMessageSource:        # MessageSource — yields a fixed event list
    def __init__(self, events): self.events = events
    async def events(self): yield from self.events

class FakeAgentClient:          # AgentClient — records commands, simulates replies
    def __init__(self, reply="[ok]", alive=True):
        self.commands = []      # outgoing: prompt / abort / extension_ui_response
        self._reply = reply
        self._alive = alive
    async def prompt_and_collect(self, message) -> str:
        self.commands.append({"type": "prompt", "message": message})
        return self._reply
    async def abort(self) -> None: self.commands.append({"type": "abort"})
    def is_alive(self) -> bool: return self._alive
    async def stop(self) -> None: self._alive = False

class FakeRouter:               # SessionRouter — returns one shared fake client
    def __init__(self, client): self.client = client
    async def get_or_create(self, chat_id): return self.client

class FakeMessageSender:        # MessageSender — records sends
    def __init__(self): self.sent = []
    async def send_message(self, chat_id, text):
        self.sent.append({"chat_id": chat_id, "text": text})
    async def close(self) -> None: pass

class AllowAllList:             # Allowlist — lets everyone through (test default)
    def allows(self, msg) -> bool: return True
```

Helpers:
```python
def msg_event(chat_id, username, text, chat_type="private", user_id=1):
    return {"message": {
        "chat": {"id": chat_id, "type": chat_type},
        "from": {"id": user_id, "username": username, "first_name": "X"},
        "text": text,
    }}
```

---

### Scenario: Receive message, relay captures reply and sends it
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given telegramy is broadcasting filtered message events over WebSocket
  And the relay is subscribed and has a PI RPC client per chat
  When a user sends "analyze BTC" on Telegram
  Then the relay resolves the chat → PI session
  And the relay sends `{"type":"prompt","message":"[from=koena] analyze BTC"}` to PI
  And PI runs its agent loop (tools, compaction, reasoning)
  And the relay reads the turn to `agent_end` and captures the final assistant text
  And the relay sends the reply via telegramy MCP `send_message(chat_id, text)`
  And the user receives the reply on Telegram

**Input table:**
| Field        | Type   | Example                    | Constraints                          |
|--------------|--------|----------------------------|--------------------------------------|
| chat.id      | string | "123456789"                | From telegramy event                 |
| chat.type    | string | "private"                  | "private" or "group"/"supergroup"    |
| from.username| string | "koena"                    | Stable, unique; may be absent        |
| from.id      | int    | 987654321                  | Allowlist key                         |
| text         | string | "analyze BTC"              | Non-empty after strip                |

**Verify (Classical school, black-box):**
```python
async def test_relay_formats_with_username_and_delivers_reply():
    pi = FakeAgentClient(reply="BTC looks bullish")
    sender = FakeMessageSender()
    relay = Relay(
        source=FakeMessageSource([msg_event("123", "koena", "analyze BTC")]),
        router=FakeRouter(pi),
        sender=sender,
        allowlist=AllowAllList(),  # or a configured allowlist containing this user
    )

    await relay.drain()

    assert pi.commands == [{"type": "prompt", "message": "[from=koena] analyze BTC"}]
    assert sender.sent == [{"chat_id": "123", "text": "BTC looks bullish"}]

async def test_relay_skips_non_message_events():
    pi = FakeAgentClient()
    relay = Relay(
        source=FakeMessageSource([{"callback_query": {"id": "abc"}}]),
        router=FakeRouter(pi), sender=FakeMessageSender(), allowlist=AllowAllList(),
    )
    await relay.drain()
    assert pi.commands == [] and sender.sent == []
```

**Also test:**
- Message with empty text after strip → ignored, no prompt sent
- User with no `username` → prefix falls back to `first_name` (e.g. `[from=X]`)
- User with neither username nor first_name → `[from=anonymous]`
- chat_id stays out of PI's prompt (assert `chat_id` not in prompt message)

---

### Scenario: Allowlist gates who can talk to HAL
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the relay is configured with a DM allowlist and groups (open or restricted)
  When a message arrives from an allowlisted sender/chat
  Then the relay processes it normally
  When a message arrives from a non-allowlisted sender/chat
  Then the relay drops it silently (no prompt, no reply, no Telegram error) and logs

**Input table (config):**
| Field       | Type        | Example                     | Constraints                |
|-------------|-------------|-----------------------------|----------------------------|
| dm_users    | set[int]    | {987654321}                 | user.id values              |
| groups[].id | int         | -100111000                  | negative for groups         |
| groups[].mode | string    | "open" \| "restricted"      | —                           |
| groups[].members | set[int]| {987654321, 111222333}   | only when mode=restricted   |

**Verify:**
```python
async def test_dm_allowed_only_for_allowlisted_user():
    pi, sender = FakeAgentClient(), FakeMessageSender()
    allowlist = Allowlist(dm_users={987654321}, groups={})
    relay = Relay(FakeMessageSource([
        msg_event("1", "stranger", "hi", user_id=999),     # not allowlisted
        msg_event("2", "koena", "hi", user_id=987654321),  # allowlisted
    ]), FakeRouter(pi), sender, allowlist)

    await relay.drain()

    assert len(pi.commands) == 1
    assert "[from=koena]" in pi.commands[0]["message"]

async def test_open_group_allows_any_member_restricted_gates_members():
    pi, sender = FakeAgentClient(), FakeMessageSender()
    allowlist = Allowlist(
        dm_users=set(),
        groups={
            -100111000: GroupConfig(mode="open"),
            -100222000: GroupConfig(mode="restricted", members={111222333}),
        },
    )
    relay = Relay(FakeMessageSource([
        msg_event(-100111000, "anyone", "hi", chat_type="group", user_id=555),       # open -> ok
        msg_event(-100222000, "alice", "hi", chat_type="group", user_id=111222333),  # member -> ok
        msg_event(-100222000, "stranger", "hi", chat_type="group", user_id=999),     # not member -> drop
    ]), FakeRouter(pi), sender, allowlist)

    await relay.drain()

    assert len(pi.commands) == 2
```

**Also test:**
- Unconfigured group chat id → dropped
- Non-private, non-group chat type (channel post) → dropped
- Allowlist loaded from config file at startup (static; restart to change)

---

### Scenario: Concurrent chats use separate PI sessions
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the relay routes chat_id → a dedicated PI process with its own session file
  When user A in chat "123" and user B in chat "456" send messages near-simultaneously
  Then each chat drives its own PI process
  And the two turns run concurrently (neither blocks the other)
  And replies route back to the correct chat

**Verify:**
```python
async def test_distinct_chats_get_distinct_sessions():
    seen_sessions = []
    class RecordingRouter:
        async def get_or_create(self, chat_id):
            client = FakeAgentClient(reply=f"reply-{chat_id}")
            seen_sessions.append(chat_id)
            return client

    relay = Relay(
        FakeMessageSource([
            msg_event("123", "koena", "hello"),
            msg_event("456", "alice", "hi"),
        ]),
        RecordingRouter(), FakeMessageSender(), AllowAllList(),
    )
    await relay.drain()

    assert set(seen_sessions) == {"123", "456"}
```

**Also test:**
- Each PI process spawned with `pi --session <sessions/hal/chat_{id}.jsonl>` (verify the CLI args)
- Two sessions never share a session file path
- A session file persists across relay restart (PI resumes it)

---

### Scenario: Second message to a busy chat waits, then runs (concurrency)
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given chat "123" is mid-turn (PI streaming)
  When a second message arrives for the same chat
  Then the relay does NOT send `prompt` while PI is streaming (that errors per RPC spec)
  And the relay serializes per-chat: the second message waits for the first turn to finish
  And the WebSocket read loop is never blocked (a third chat can still be read meanwhile)
  And once PI is idle, the second message is sent as a fresh `prompt`

**Verify:**
```python
async def test_same_chat_messages_are_serialized_not_interleaved():
    pi = FakeAgentClient(reply="r")
    relay = Relay(
        FakeMessageSource([
            msg_event("123", "koena", "first"),
            msg_event("123", "koena", "second"),
        ]),
        FakeRouter(pi), FakeMessageSender(), AllowAllList(),
    )
    await relay.drain()

    # Both delivered, in order, as separate prompts (never concurrent on one process)
    messages = [c["message"] for c in pi.commands]
    assert messages == ["[from=koena] first", "[from=koena] second"]

async def test_read_loop_not_blocked_by_long_turn():
    # Slow client on chat "123"; a fast client on "456" should still complete
    # promptly, proving the read loop dispatched both concurrently.
    ...
```

**Also test:**
- Two different chats run concurrently (parallel), not serially
- `follow_up`/`steer` not used in MVP (lock-then-prompt-after-idle is the default)
  — document as the future "queue within running turn" enhancement
- A turn that hits `TURN_TIMEOUT` is aborted (not left streaming): assert an
  `abort` command was issued and the per-chat lock was released so the next
  message is accepted. The warm process is preserved when abort succeeds. (The
  abort mechanics and wedge-escalation are covered in
  `tests/infrastructure/test_pi_rpc_client.py`.)

---

### Scenario: PI requests approval mid-turn (no deadlock)
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given PI's extensions can emit `extension_ui_request` (select/confirm/input)
  And in RPC mode such a request BLOCKS until the client replies
  When PI emits an approval request during a turn
  Then the relay's reader loop handles it (MVP: auto-responds per policy)
  And PI unblocks and the turn continues to `agent_end`
  And the reply is delivered normally (no hang)

**Verify (Relay-level outcome — the turn completes despite a UI request):**
```python
async def test_turn_completes_when_pi_emits_ui_request():
    # The Relay treats prompt_and_collect as a black box: if the AgentClient
    # returns text, the turn completed (the UI request was handled internally).
    pi = FakeAgentClient(reply="done")
    sender = FakeMessageSender()
    relay = Relay(
        FakeMessageSource([msg_event("123", "koena", "do it")]),
        FakeRouter(pi), sender, AllowAllList(),
    )
    await relay.drain()
    assert sender.sent == [{"chat_id": "123", "text": "done"}]
```

**The UI-request mechanics themselves are tested at the infrastructure layer**
(`tests/infrastructure/test_pi_rpc_client.py` with a fake subprocess), because
`extension_ui_request` handling lives inside `PIRpcClient`, behind the
`AgentClient` interface. There assert:
- an injected `extension_ui_request {method:confirm}` produces an
  `extension_ui_response {confirmed:true}` on PI's stdin and the turn completes
- `select`/`input`/`editor` requests auto-resolved with a permissive default
- Fire-and-forget UI requests (`notify`, `setStatus`, `setWidget`) expect no response
- (Future, not MVP) confirm rendered as Telegram inline keyboard, callback_query → `extension_ui_response`

---

### Scenario: Failure produces an error reply, never silence
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the relay is processing a message
  When PI rejects the prompt (e.g. invalid input) OR the send to telegramy fails
  Then the relay does NOT crash
  And the relay releases the per-chat lock (the chat is not bricked)
  And the user receives a short error reply in the chat (best-effort)
  And the relay continues processing other messages

**Verify:**
```python
async def test_pi_failure_yields_error_reply_not_crash():
    class ExplodingAgentClient(FakeAgentClient):
        async def prompt_and_collect(self, message):
            raise RuntimeError("PI rejected prompt: bad input")

    pi = ExplodingAgentClient()
    sender = FakeMessageSender()
    relay = Relay(
        FakeMessageSource([msg_event("123", "koena", "oops")]),
        FakeRouter(pi), sender, AllowAllList(),
    )
    await relay.drain()  # must not raise

    # An error reply was sent to the user (not silence)
    assert len(sender.sent) == 1
    assert sender.sent[0]["chat_id"] == "123"
    assert "wrong" in sender.sent[0]["text"].lower()
```

**Also test:**
- Sender failure too → logged, relay still alive (the error-reply send is itself
  wrapped so a total outage doesn’t escalate)
- A subsequent message to the same chat still works (the lock was released)
- A dead PI subprocess (`is_alive()==False`) is restarted by the router on next
  `get_or_create` for that chat (ties to the “Relay survives PI restart” scenario)

---

### Scenario: PI uses kapsula / webdown / finbar
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given PI has kapsula/webdown/finbar MCP configured
  When a user asks a question requiring those tools
  Then PI calls the relevant MCP tools during its turn
  And PI synthesizes the answer
  And the relay captures PI's final text and sends it via telegramy

**Note:** No relay code involved — this verifies PI config wiring, not relay
logic. Cover with an integration smoke test that PI starts with the HAL config
and `get_commands` / a trivial prompt succeeds.

---

### Scenario: PI handles /reset command
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given PI is running in RPC mode with HAL config
  When a user sends "/reset" on Telegram
  Then the relay forwards it as a prompt: `[from=koena] /reset`
  And PI's system prompt recognizes /reset and confirms via the captured reply

**Note (future enhancement):** `/reset` could map directly to the RPC
`new_session` command (instant, no tokens), and `/model X` to `set_model`.
Relay-side command interception is a documented Slice 2+ enhancement; for now
commands are forwarded as prompts to keep the relay thin.

---

### Scenario: Relay survives PI restart
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given the relay manages a PI RPC subprocess per chat
  When one PI subprocess crashes (stdout closes unexpectedly)
  Then the relay detects the subprocess exit
  And the relay logs the error
  And the relay restarts a fresh PI subprocess for that chat, pointing at the same session file
  And PI resumes from its persisted session
  And the relay's other chats are unaffected (process isolation)

**Also test:**
- `proc.wait()` is bounded by a timeout (does not hang on a stuck PI)
- Orphaned subprocesses are terminated on relay shutdown
- SIGTERM to relay → graceful PI shutdown before exit
