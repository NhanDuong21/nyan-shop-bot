"""Global test safety policy: business-runtime network is loopback-only."""

import ipaddress
import socket
from collections.abc import Iterator
from typing import Any

import pytest


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_non_loopback_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reject supplier, bank, Telegram, and other non-local socket connections."""
    original_connect = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        if isinstance(address, tuple) and address and _is_loopback(address[0]):
            return original_connect(sock, address)
        if isinstance(address, str):
            return original_connect(sock, address)
        raise RuntimeError(f"Outbound network blocked during tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield
