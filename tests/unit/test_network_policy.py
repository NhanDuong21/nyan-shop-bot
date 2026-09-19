"""Prove that runtime tests cannot reach supplier or Telegram hosts."""

import socket

import pytest


def test_non_loopback_network_is_blocked() -> None:
    sock = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="Outbound network blocked"):
            sock.connect(("api.telegram.org", 443))
    finally:
        sock.close()
