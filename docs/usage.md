# Usage

## Running

```bash
python -m relaypi.main
```

The relay connects to telegramy's WebSocket, subscribes to message events, and
waits. On each allowed message it: resolves the chat → PI session (spawning PI
if needed), sends the formatted prompt, reads the turn to completion, captures
the final text, and sends it back via telegramy's MCP.

Stop with **Ctrl+C** (Windows) or your process supervisor's stop signal. The
relay waits for in-flight turns, stops all PI subprocesses (bounded, then
killed), and closes the MCP client.

## Logs

Default level is `INFO` (`logging.basicConfig` in `main.py`). Significant
events: allowlist drops, PI client start/stop, abort escalation, reader-loop
crashes. Raise to `DEBUG` by setting `LOGGING=DEBUG` or editing `main.py` if
you need the full JSON-RPC traffic.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Messages ignored, no reply | Sender not in allowlist | Check `config/allowlist.yaml`; message logs say "dropped message from …" |
| `pi` not found / spawn error | `RELAYPI_PI_BIN` wrong | Set `RELAYPI_PI_BIN` to the full path (Windows: the `pi.cmd` shim) |
| PI starts but `.pi/SYSTEM.md` not loaded | Project dir not trusted | Spawn uses `-a`; or pre-trust via an interactive `pi` in `hal/` |
| "PI stream closed" errors | PI subprocess crashed | The relay auto-restarts on the next message; check PI's own logs for the crash cause |
| Send fails ("telegramy MCP error") | telegramy MCP server down | Ensure `TELEGRAMY_MCP_TRANSPORT=http` and the server is reachable at `RELAYPI_MCP_URL` |
| Hangs forever on a turn | Unlikely — `TURN_TIMEOUT` (600s) + `abort` guards this | If seen, check `abort_timeout` (15s) escalation in logs |

## Verifying the pieces without Telegram

```bash
# PI profile loads?
cd hal && pi -a --print "hello"

# telegramy reachable?
curl http://localhost:8005/mcp   # MCP endpoint

# Full unit/integration suite
pytest
```
