"""Tests for PIRpcClient — Scenario 5 (approval mechanics + protocol).

Classical school: a FakeStreamTransport (real demand-driven PI behaviour) feeds
scripted JSONL lines and records the client's outgoing commands. We assert on
outcomes (returned text, captured commands, raised errors) — never interactions.

Covers the protocol traps from docs/development.md:
  * await ``response`` before ``agent_end`` (rejection does not hang)
  * ``extension_ui_request`` is always answered (no deadlock)
"""

import asyncio

import pytest

from hal_relay.infrastructure.adapters.pi_rpc_client import PIRpcClient
from tests.fakes.fake_stream_transport import FakeStreamTransport


async def _start(transport: FakeStreamTransport) -> PIRpcClient:
    client = PIRpcClient(transport=transport, turn_timeout=2.0, abort_timeout=1.0)
    await client.start()
    return client


def _resp(cmd_id: int, success: bool, **data) -> dict:
    r = {"type": "response", "id": cmd_id, "command": "prompt", "success": success}
    r.update(data)
    return r


async def test_prompt_collect_returns_final_assistant_text():
    transport = FakeStreamTransport()
    # Command 1 = prompt: accepted, one text delta, agent_end.
    transport.script_response(
        1,
        [
            {"type": "response", "id": 1, "command": "prompt", "success": True},
            {"type": "agent_end", "messages": []},
        ],
    )
    # Command 2 = get_last_assistant_text.
    transport.script_response(
        2,
        [
            {
                "type": "response",
                "id": 2,
                "command": "get_last_assistant_text",
                "success": True,
                "data": {"text": "BTC looks bullish"},
            },
        ],
    )

    client = await _start(transport)
    try:
        text = await client.prompt_and_collect("[from=koena] analyze BTC")
    finally:
        await client.stop()

    assert text == "BTC looks bullish"
    # Both commands were sent, with the expected message and types.
    assert transport.writes[0] == {
        "id": 1,
        "type": "prompt",
        "message": "[from=koena] analyze BTC",
    }
    assert transport.writes[1]["type"] == "get_last_assistant_text"


async def test_rejected_prompt_raises_does_not_hang():
    transport = FakeStreamTransport()
    transport.script_response(
        1,
        [
            {
                "type": "response",
                "id": 1,
                "command": "prompt",
                "success": False,
                "error": "bad input",
            },
        ],
    )

    client = await _start(transport)
    try:
        with pytest.raises(RuntimeError, match="PI rejected prompt"):
            await client.prompt_and_collect("[from=koena] oops")
    finally:
        await client.stop()


async def test_confirm_ui_request_is_auto_responded_and_turn_completes():
    transport = FakeStreamTransport()
    # Mid-turn, PI emits an approval request BEFORE agent_end. In RPC mode this
    # BLOCKS until answered — the client must send extension_ui_response.
    transport.script_response(
        1,
        [
            {"type": "response", "id": 1, "command": "prompt", "success": True},
            {
                "type": "extension_ui_request",
                "id": "u1",
                "method": "confirm",
                "title": "ok?",
            },
            {"type": "agent_end", "messages": []},
        ],
    )
    transport.script_response(
        2,
        [
            {
                "type": "response",
                "id": 2,
                "command": "get_last_assistant_text",
                "success": True,
                "data": {"text": "done"},
            },
        ],
    )

    client = await _start(transport)
    try:
        text = await client.prompt_and_collect("[from=koena] do it")
    finally:
        await client.stop()

    # The turn completed (no deadlock) and the response was auto-confirmed.
    assert text == "done"
    ui_responses = [
        w for w in transport.writes if w.get("type") == "extension_ui_response"
    ]
    assert ui_responses == [
        {"type": "extension_ui_response", "id": "u1", "confirmed": True}
    ]


async def test_select_input_editor_requests_auto_responded_with_empty_value():
    for method in ("select", "input", "editor"):
        transport = FakeStreamTransport()
        transport.script_response(
            1,
            [
                {"type": "response", "id": 1, "command": "prompt", "success": True},
                {"type": "extension_ui_request", "id": "u1", "method": method},
                {"type": "agent_end", "messages": []},
            ],
        )
        transport.script_response(
            2,
            [
                {
                    "type": "response",
                    "id": 2,
                    "command": "get_last_assistant_text",
                    "success": True,
                    "data": {"text": "ok"},
                },
            ],
        )

        client = await _start(transport)
        try:
            await client.prompt_and_collect("[from=koena] x")
        finally:
            await client.stop()

        ui = [w for w in transport.writes if w.get("type") == "extension_ui_response"]
        assert ui == [
            {"type": "extension_ui_response", "id": "u1", "value": ""}
        ], method


async def test_pi_dying_mid_turn_raises_and_does_not_hang():
    # PI accepts the prompt then its stdout closes (crash). The reader's finally
    # synthesizes an agent_end so the turn's event loop exits; but the following
    # get_last_assistant_text command can never be answered (reader is dead).
    # The client MUST raise rather than hang forever on a dead stream.
    transport = FakeStreamTransport()
    transport.script_response(
        1,
        [{"type": "response", "id": 1, "command": "prompt", "success": True}],
    )
    transport.script_eof_after(1)  # crash immediately after the prompt ack

    client = await _start(transport)
    try:
        from hal_relay.core.domain.agent_error import AgentError

        with pytest.raises(AgentError, match="PI stream closed"):
            await asyncio.wait_for(
                client.prompt_and_collect("[from=koena] hi"), timeout=2.0
            )
    finally:
        await client.stop()

    # Observable: the client is marked dead so the router can restart it.
    assert client.is_alive() is False


async def test_event_queue_is_bounded_and_does_not_drop_on_normal_turn():
    # M4: the in-flight event queue is bounded (MAX_QUEUED_EVENTS) so a chatty
    # turn can't grow memory unboundedly. A normal turn that emits a burst of
    # events and then agent_end must still complete and deliver every event to
    # the consumer (the bound applies backpressure to the reader, not a drop).
    from hal_relay.infrastructure.adapters.pi_rpc_client import MAX_QUEUED_EVENTS

    burst = [{"type": "tool_execution_update", "toolCallId": str(i)} for i in range(50)]
    transport = FakeStreamTransport()
    transport.script_response(
        1,
        [
            {"type": "response", "id": 1, "command": "prompt", "success": True},
            *burst,
            {"type": "agent_end"},
        ],
    )
    transport.script_response(
        2,
        [
            {
                "type": "response",
                "id": 2,
                "command": "get_last_assistant_text",
                "success": True,
                "data": {"text": "done"},
            }
        ],
    )

    client = await _start(transport)
    try:
        assert MAX_QUEUED_EVENTS > 0  # the bound exists
        text = await asyncio.wait_for(
            client.prompt_and_collect("[from=koena] hi"), timeout=2.0
        )
    finally:
        await client.stop()

    # Turn completed normally despite the bounded queue.
    assert text == "done"
