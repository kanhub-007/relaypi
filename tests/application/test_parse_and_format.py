"""Tests for parse_inbound + format_prompt (Scenario 1 core).

These are the pure functions at the head of the relay pipeline: a telegramy
WebSocket event -> an InboundMessage DTO, and an InboundMessage -> the
display-only prompt string sent to PI.

Black-box: assertions are on returned values, not on internals.
"""

from relaypi.core.application.format_prompt import format_prompt
from relaypi.core.application.parse import parse_inbound


def _msg_event(
    chat_id: str = "1",
    username: str | None = "alice",
    first_name: str = "X",
    text: str = "analyze BTC",
    user_id: int = 1,
) -> dict:
    """Build a telegramy-shaped message event for tests (real format)."""
    sender: dict = {"id": user_id, "first_name": first_name}
    if username is not None:
        sender["username"] = username
    return {
        "type": "message",
        "event": {
            "chat_id": chat_id,
            "from_user": sender,
            "text": text,
        },
    }


# --- parse_inbound ---


def test_parse_extracts_message_fields():
    msg = parse_inbound(_msg_event())

    assert msg is not None
    assert msg.chat_id == "1"
    # chat_type is inferred: chat_id matches sender_user_id -> "private"
    assert msg.chat_type == "private"
    assert msg.sender_user_id == 1
    assert msg.sender_username == "alice"
    assert msg.sender_first_name == "X"
    assert msg.text == "analyze BTC"


def test_parse_infers_group_chat_type():
    # Group chats have negative ids not matching the sender.
    msg = parse_inbound(_msg_event(chat_id="-100111000", user_id=555))
    assert msg is not None
    assert msg.chat_type == "group"


def test_parse_returns_none_for_non_message_event():
    assert parse_inbound({"callback_query": {"id": "abc"}}) is None


def test_parse_returns_none_for_non_message_type():
    assert parse_inbound({"type": "callback_query", "event": {"text": "x"}}) is None


def test_parse_returns_none_for_whitespace_only_text():
    assert parse_inbound(_msg_event(text="   ")) is None


def test_parse_returns_none_when_text_missing():
    event = {"type": "message", "event": {"chat_id": "1", "from_user": {"id": 1}}}
    assert parse_inbound(event) is None


def test_parse_returns_none_when_sender_id_missing():
    # No sender id -> can never be allowlisted -> fail closed at parse time.
    event = {
        "type": "message",
        "event": {
            "chat_id": "1",
            "from_user": {"first_name": "X"},
            "text": "hi",
        },
    }
    assert parse_inbound(event) is None


def test_parse_returns_none_when_sender_id_not_an_int():
    # A non-numeric id must not raise (which would be masked downstream); it
    # returns None so the message is dropped cleanly.
    event = {
        "type": "message",
        "event": {
            "chat_id": "1",
            "from_user": {"id": "abc"},
            "text": "hi",
        },
    }
    assert parse_inbound(event) is None


def test_parse_strips_surrounding_whitespace_from_text():
    assert parse_inbound(_msg_event(text="  hello  ")).text == "hello"


# --- format_prompt ---


def test_format_uses_username_when_present():
    msg = parse_inbound(_msg_event(username="alice", text="hi"))
    assert format_prompt(msg).text == "[from=alice] hi"


def test_format_falls_back_to_first_name_when_no_username():
    msg = parse_inbound(_msg_event(username=None, first_name="Alice", text="hi"))
    assert format_prompt(msg).text == "[from=Alice] hi"


def test_format_uses_anonymous_when_no_username_or_first_name():
    event = {
        "type": "message",
        "event": {
            "chat_id": "1",
            "from_user": {"id": 1},
            "text": "hi",
        },
    }
    msg = parse_inbound(event)
    assert format_prompt(msg).text == "[from=anonymous] hi"


def test_chat_id_never_enters_formatted_prompt():
    msg = parse_inbound(_msg_event(chat_id="999", text="hi"))
    assert "999" not in format_prompt(msg).text
