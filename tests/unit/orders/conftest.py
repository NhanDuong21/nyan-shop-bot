"""Order tests prohibit every socket and DNS attempt, including loopback."""

from __future__ import annotations

import inspect
import socket
from collections.abc import Iterator
from typing import NoReturn

import pytest


@pytest.fixture(autouse=True)
def block_all_order_test_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original_connect = socket.socket.connect

    def blocked(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Order orchestration attempted outbound network access.")

    def guarded_connect(sock: socket.socket, address: object) -> object:
        # Windows asyncio builds its wakeup socketpair through a numeric loopback
        # connection. Permit only that local runtime plumbing; DNS and every
        # non-loopback destination remain impossible in this suite.
        building_asyncio_socketpair = any(
            frame.function == "_fallback_socketpair" and frame.filename.endswith("socket.py")
            for frame in inspect.stack()
        )
        if building_asyncio_socketpair:
            return original_connect(sock, address)
        raise AssertionError("Order orchestration attempted outbound network access.")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    yield
