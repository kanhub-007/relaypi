"""Tests for main._is_connection_error — H3 (classify by class, not name)."""

import httpx
import websockets

from hal_relay.main import _is_connection_error


def test_socket_errors_classified_as_connection_errors():
    assert _is_connection_error(ConnectionRefusedError("x")) is True
    assert _is_connection_error(ConnectionResetError("x")) is True
    assert _is_connection_error(OSError("x")) is True


def test_websockets_and_httpx_errors_classified_as_connection_errors():
    # Covered by name before; now classified by class so they survive a rename.
    assert _is_connection_error(httpx.ConnectError("telegramy down")) is True
    # Class-membership is what matters; assert via issubclass for the ones that
    # need awkward constructor args.
    assert issubclass(websockets.InvalidHandshake, Exception)
    assert issubclass(websockets.InvalidStatus, Exception)


def test_unrelated_errors_not_classified_as_connection_errors():
    assert _is_connection_error(ValueError("not a connection issue")) is False
    assert _is_connection_error(KeyError("nope")) is False
    assert _is_connection_error(RuntimeError("PI rejected prompt")) is False
