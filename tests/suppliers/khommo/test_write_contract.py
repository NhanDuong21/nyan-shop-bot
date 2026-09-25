"""KhoMMO create/status conformance with injected fakes only."""

from __future__ import annotations

import json
import logging
import socket
from collections.abc import Iterable
from pathlib import Path

import pytest

from nyan_shop_bot.suppliers.khommo import (
    KhoMmoHttpTransport,
    KhoMmoResponse,
    KhoMmoToken,
)
from nyan_shop_bot.suppliers.khommo.write_contract import (
    CreateOrder,
    KhoMmoOfflineOrderAdapter,
    OfflineOrderJournal,
    OfflineOrderRequest,
    OrderContractError,
    UnknownOrderState,
)


class FakeTransport:
    def __init__(self, outcomes: Iterable[KhoMmoResponse | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.requests: list[OfflineOrderRequest] = []
        self.journal: OfflineOrderJournal | None = None
        self.observed_state: list[UnknownOrderState] = []

    async def send(self, request: OfflineOrderRequest, *, timeout_seconds: float) -> KhoMmoResponse:
        self.requests.append(request)
        if self.journal is not None:
            self.observed_state.append(self.journal.state("local-operation-1").state)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def subject(
    tmp_path: Path, outcomes: Iterable[KhoMmoResponse | Exception]
) -> tuple[KhoMmoOfflineOrderAdapter, FakeTransport, OfflineOrderJournal]:
    transport = FakeTransport(outcomes)
    journal = OfflineOrderJournal(tmp_path / "khommo-offline.sqlite3")
    transport.journal = journal
    adapter = KhoMmoOfflineOrderAdapter(
        token=KhoMmoToken("synthetic-token"),
        transport=transport,
        journal=journal,
    )
    adapter.prepare("local-operation-1", CreateOrder("synthetic-product", 1, "VND"))
    return adapter, transport, journal


@pytest.mark.asyncio
async def test_create_model_exact_documented_body_and_one_dispatch(tmp_path: Path) -> None:
    adapter, transport, journal = subject(tmp_path, [KhoMmoResponse(200, b"private-body")])
    assert journal.state("local-operation-1").state is UnknownOrderState.NOT_DISPATCHED
    result = await adapter.create_once("local-operation-1")
    assert result.state is UnknownOrderState.UNKNOWN_RECONCILING
    assert result.http_status == 200
    assert transport.observed_state == [UnknownOrderState.UNKNOWN_RECONCILING]
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url.endswith("/api/partner/v1/orders")
    assert json.loads(request.body) == {
        "productId": "synthetic-product",
        "quantity": 1,
        "paymentMode": "VND",
    }
    assert set(json.loads(request.body)) == {"productId", "quantity", "paymentMode"}
    assert request.headers["Content-Type"] == "application/json"
    assert (await adapter.create_once("local-operation-1")).state is (
        UnknownOrderState.UNKNOWN_RECONCILING
    )
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("private timeout"),
        ConnectionError("private socket"),
        KhoMmoResponse(502, b"private error"),
        KhoMmoResponse(503, b"private error"),
    ],
)
@pytest.mark.asyncio
async def test_uncertain_outcome_has_no_second_post_even_after_restart(
    tmp_path: Path,
    failure: KhoMmoResponse | Exception,
) -> None:
    adapter, transport, journal = subject(tmp_path, [failure])
    first = await adapter.create_once("local-operation-1")
    assert first.state is UnknownOrderState.UNKNOWN_RECONCILING
    restarted = KhoMmoOfflineOrderAdapter(
        token=KhoMmoToken("synthetic-token"),
        transport=transport,
        journal=OfflineOrderJournal(tmp_path / "khommo-offline.sqlite3"),
    )
    second = await restarted.create_once("local-operation-1")
    assert second.state is UnknownOrderState.UNKNOWN_RECONCILING
    assert len(transport.requests) == 1
    assert journal.state("local-operation-1").state is UnknownOrderState.UNKNOWN_RECONCILING


@pytest.mark.asyncio
async def test_lost_response_without_order_no_cannot_query_or_retry(tmp_path: Path) -> None:
    adapter, transport, _ = subject(tmp_path, [TimeoutError()])
    assert (await adapter.create_once("local-operation-1")).state is (
        UnknownOrderState.UNKNOWN_RECONCILING
    )
    with pytest.raises(OrderContractError):
        await adapter.get_known_order_status("")
    assert len(transport.requests) == 1
    assert (await adapter.create_once("local-operation-1")).state is (
        UnknownOrderState.UNKNOWN_RECONCILING
    )
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_known_order_status_get_exposes_no_undocumented_delivery(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, transport, journal = subject(
        tmp_path, [KhoMmoResponse(200, b'{"data":{"delivery":"private-account-material"}}')]
    )
    with caplog.at_level(logging.DEBUG):
        outcome = await adapter.get_known_order_status("KNOWN_123")
    assert outcome.state is UnknownOrderState.UNKNOWN_RECONCILING
    assert outcome.http_status == 200
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.url.endswith("/orders/KNOWN_123")
    assert request.body == b""
    rendered = " ".join((repr(adapter), repr(request), repr(outcome), repr(journal), caplog.text))
    assert "private-account-material" not in rendered
    assert "synthetic-token" not in rendered


def test_request_validation_and_same_operation_body_are_fail_closed(tmp_path: Path) -> None:
    adapter, transport, journal = subject(tmp_path, [])
    for order in (("", 1, "VND"), ("x", 0, "VND"), ("x", 1, "VND_ONLY"), ("x", True, "CREDIT")):
        with pytest.raises(OrderContractError):
            CreateOrder(*order)
    with pytest.raises(OrderContractError):
        adapter.prepare("local-operation-1", CreateOrder("another-product", 1, "VND"))
    assert transport.requests == []
    assert journal.state("local-operation-1").state is UnknownOrderState.NOT_DISPATCHED


@pytest.mark.asyncio
async def test_real_transport_remains_get_only_and_no_socket_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unexpected supplier socket")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    adapter, transport, _ = subject(tmp_path, [KhoMmoResponse(502)])
    assert (await adapter.create_once("local-operation-1")).state is (
        UnknownOrderState.UNKNOWN_RECONCILING
    )
    real_transport = KhoMmoHttpTransport()
    with pytest.raises(Exception, match="GET only"):
        await real_transport.send(transport.requests[0], timeout_seconds=1)  # type: ignore[arg-type]
    await real_transport.aclose()
