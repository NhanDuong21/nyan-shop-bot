"""Exact offline POST contract tests. Every transport is an injected fake."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import socket
from collections.abc import Iterable
from pathlib import Path

import pytest

from nyan_shop_bot.suppliers.vietshare import (
    VietShareCredentials,
    VietShareHttpTransport,
    VietShareRequest,
    VietShareResponse,
)
from nyan_shop_bot.suppliers.vietshare.write_journal import JournalConflict, SqliteWriteJournal
from nyan_shop_bot.suppliers.vietshare.write_orders import (
    OrderPurchase,
    VietShareOfflineWriteAdapter,
    WriteContractError,
    WriteState,
    parse_order_response,
)


def completed_body(
    *, key: str = "local-order-0001", account: str = "private-delivery-marker"
) -> bytes:
    return json.dumps(
        {
            "success": True,
            "order": {
                "order_code": "SYNTHETIC-ORDER-1",
                "status": "completed",
                "channel": "api",
                "product": {"id": 7, "name": "Synthetic offline item"},
                "quantity": 1,
                "unit_price": 20_000,
                "unit_prices": [20_000],
                "price_breakdown": [{"quantity": 1, "unit_price": 20_000, "subtotal": 20_000}],
                "total_amount": 20_000,
                "discount_amount": 0,
                "accounts": [account],
                "idempotency_key": key,
                "created_at": "2026-09-25T00:00:00+00:00",
                "delivered_at": "2026-09-25T00:00:00+00:00",
            },
        },
        separators=(",", ":"),
    ).encode()


class FakeTransport:
    def __init__(self, outcomes: Iterable[VietShareResponse | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.requests: list[VietShareRequest] = []
        self.observed_states: list[str] = []
        self.journal: SqliteWriteJournal | None = None

    async def send(self, request: VietShareRequest, *, timeout_seconds: float) -> VietShareResponse:
        self.requests.append(request)
        if self.journal is not None:
            record = self.journal.get("local-operation-1")
            assert record is not None
            self.observed_states.append(record.state)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def subject(
    tmp_path: Path, outcomes: Iterable[VietShareResponse | Exception]
) -> tuple[VietShareOfflineWriteAdapter, FakeTransport, SqliteWriteJournal]:
    transport = FakeTransport(outcomes)
    journal = SqliteWriteJournal(tmp_path / "write-journal.sqlite3")
    transport.journal = journal
    timestamps = iter((1000, 1001, 1002))
    nonces = iter(("synthetic-nonce-0001", "synthetic-nonce-0002", "synthetic-nonce-0003"))
    adapter = VietShareOfflineWriteAdapter(
        credentials=VietShareCredentials("synthetic-id", "synthetic-secret"),
        transport=transport,
        journal=journal,
        clock=lambda: next(timestamps),
        nonce_source=lambda: next(nonces),
    )
    adapter.prepare("local-operation-1", "local-order-0001", OrderPurchase(7, 1, 20_000))
    return adapter, transport, journal


@pytest.mark.asyncio
async def test_exact_raw_bytes_hmac_and_durable_prepare_before_post(tmp_path: Path) -> None:
    adapter, transport, journal = subject(
        tmp_path, [VietShareResponse(status_code=200, body=completed_body())]
    )
    record = SqliteWriteJournal(tmp_path / "write-journal.sqlite3").get("local-operation-1")
    assert record is not None and record.state == "PREPARED"
    outcome = await adapter.submit("local-operation-1")
    assert outcome.state is WriteState.COMPLETED
    assert transport.observed_states == ["DISPATCHING"]
    request = transport.requests[0]
    assert request.method == "POST" and request.path_with_query == "/v1/orders"
    assert request.body == record.body
    assert request.headers["Idempotency-Key"] == record.idempotency_key
    canonical = (
        b"1000|synthetic-nonce-0001|POST|/v1/orders|"
        + hashlib.sha256(record.body).hexdigest().encode()
    )
    assert (
        request.headers["X-Signature"]
        == hmac.new(b"synthetic-secret", canonical, hashlib.sha256).hexdigest()
    )
    assert journal.get("local-operation-1").state == "COMPLETED"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_timeout_recovery_reuses_exact_key_body_with_fresh_auth(tmp_path: Path) -> None:
    adapter, transport, journal = subject(
        tmp_path,
        [TimeoutError("private timeout text"), VietShareResponse(200, body=completed_body())],
    )
    first = await adapter.submit("local-operation-1")
    assert first.state is WriteState.UNKNOWN
    assert journal.get("local-operation-1").state == "UNKNOWN"  # type: ignore[union-attr]
    second = await adapter.submit("local-operation-1")
    assert second.state is WriteState.COMPLETED
    sent_first, sent_second = transport.requests
    assert sent_first.body == sent_second.body
    assert sent_first.headers["Idempotency-Key"] == sent_second.headers["Idempotency-Key"]
    for name in ("X-Timestamp", "X-Nonce", "X-Signature"):
        assert sent_first.headers[name] != sent_second.headers[name]
    assert transport.observed_states == ["DISPATCHING", "DISPATCHING"]


@pytest.mark.asyncio
async def test_202_and_request_in_progress_preserve_retry_after(tmp_path: Path) -> None:
    adapter, transport, journal = subject(
        tmp_path,
        [
            VietShareResponse(202, headers={"Retry-After": "7"}),
            VietShareResponse(
                409,
                headers={"Retry-After": "4"},
                body=b'{"detail":{"code":"REQUEST_IN_PROGRESS","message":"private"}}',
            ),
            VietShareResponse(200, body=completed_body()),
        ],
    )
    first = await adapter.submit("local-operation-1")
    second = await adapter.submit("local-operation-1")
    third = await adapter.submit("local-operation-1")
    assert (first.state, first.retry_after_seconds) == (WriteState.IN_PROGRESS, 7.0)
    assert (second.state, second.retry_after_seconds) == (WriteState.IN_PROGRESS, 4.0)
    assert third.state is WriteState.COMPLETED
    assert len({r.headers["Idempotency-Key"] for r in transport.requests}) == 1
    assert len({r.body for r in transport.requests}) == 1
    assert journal.get("local-operation-1").state == "COMPLETED"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_mismatch_is_explicit_and_never_retried(tmp_path: Path) -> None:
    adapter, transport, journal = subject(
        tmp_path,
        [
            VietShareResponse(
                409, body=b'{"detail":{"code":"IDEMPOTENCY_MISMATCH","message":"private"}}'
            )
        ],
    )
    first = await adapter.submit("local-operation-1")
    second = await adapter.submit("local-operation-1")
    assert first.state is second.state is WriteState.MISMATCH
    assert len(transport.requests) == 1
    assert journal.get("local-operation-1").state == "MISMATCH"  # type: ignore[union-attr]


def test_same_key_cannot_bind_changed_payload_or_operation(tmp_path: Path) -> None:
    adapter, _, journal = subject(tmp_path, [])
    adapter.prepare("local-operation-1", "local-order-0001", OrderPurchase(7, 1, 20_000))
    with pytest.raises(JournalConflict):
        adapter.prepare("local-operation-1", "local-order-0001", OrderPurchase(7, 1, 30_000))
    with pytest.raises(JournalConflict):
        adapter.prepare("local-operation-2", "local-order-0001", OrderPurchase(7, 1, 20_000))
    assert journal.get("local-operation-1").state == "PREPARED"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_interrupted_dispatch_requires_explicit_reconciliation(tmp_path: Path) -> None:
    adapter, transport, journal = subject(tmp_path, [VietShareResponse(200, body=completed_body())])
    assert journal.begin_attempt("local-operation-1") is not None
    assert (await adapter.submit("local-operation-1")).state is WriteState.IN_PROGRESS
    assert transport.requests == []
    journal.mark_interrupted_unknown("local-operation-1")
    assert (await adapter.submit("local-operation-1")).state is WriteState.COMPLETED
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_delivery_material_stays_out_of_repr_errors_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    marker = "private-delivery-marker"
    adapter, transport, journal = subject(
        tmp_path, [VietShareResponse(200, body=completed_body(account=marker))]
    )
    with caplog.at_level(logging.DEBUG):
        outcome = await adapter.submit("local-operation-1")
    assert outcome.order is not None
    assert outcome.order.accounts.values == (marker,)
    rendered = " ".join(
        (
            repr(adapter),
            repr(outcome),
            repr(outcome.order),
            repr(outcome.order.accounts),
            repr(journal.get("local-operation-1")),
            repr(transport.requests[0]),
            caplog.text,
        )
    )
    assert marker not in rendered
    with pytest.raises(WriteContractError) as caught:
        parse_order_response(
            b'{"success":true,"order":{"accounts":["private-delivery-marker"]}}',
            key="local-order-0001",
            purchase=OrderPurchase(7, 1, 20_000),
        )
    assert marker not in str(caught.value)


@pytest.mark.asyncio
async def test_invalid_200_is_unknown_and_never_claimed_delivered(tmp_path: Path) -> None:
    adapter, _, journal = subject(
        tmp_path,
        [VietShareResponse(200, body=b'{"success":true,"order":{"accounts":["private"]}}')],
    )
    assert (await adapter.submit("local-operation-1")).state is WriteState.UNKNOWN
    assert journal.get("local-operation-1").state == "UNKNOWN"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_status_and_delivery_get_uses_documented_order_code_and_empty_body(
    tmp_path: Path,
) -> None:
    adapter, transport, _ = subject(
        tmp_path,
        [
            VietShareResponse(200, body=completed_body()),
            VietShareResponse(200, body=completed_body()),
        ],
    )
    assert (await adapter.submit("local-operation-1")).state is WriteState.COMPLETED
    lookup = await adapter.get_delivered_order("local-operation-1")
    assert lookup.state is WriteState.COMPLETED
    assert lookup.order is not None
    assert lookup.order.accounts.values == ("private-delivery-marker",)
    request = transport.requests[1]
    assert request.method == "GET"
    assert request.path_with_query == "/v1/orders/SYNTHETIC-ORDER-1"
    assert request.body == b""
    assert "Idempotency-Key" not in request.headers
    canonical = (
        b"1001|synthetic-nonce-0002|GET|/v1/orders/SYNTHETIC-ORDER-1|"
        + hashlib.sha256(b"").hexdigest().encode()
    )
    assert (
        request.headers["X-Signature"]
        == hmac.new(b"synthetic-secret", canonical, hashlib.sha256).hexdigest()
    )


@pytest.mark.asyncio
async def test_502_remains_unknown_and_recovery_keeps_one_commercial_key(tmp_path: Path) -> None:
    adapter, transport, _ = subject(
        tmp_path,
        [VietShareResponse(502), VietShareResponse(200, body=completed_body())],
    )
    assert (await adapter.submit("local-operation-1")).state is WriteState.UNKNOWN
    assert len(transport.requests) == 1
    assert (await adapter.submit("local-operation-1")).state is WriteState.COMPLETED
    assert len(transport.requests) == 2
    assert len({request.headers["Idempotency-Key"] for request in transport.requests}) == 1


@pytest.mark.asyncio
async def test_http_transport_still_refuses_post_and_tests_have_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unexpected supplier socket")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    adapter, transport, _ = subject(tmp_path, [VietShareResponse(200, body=completed_body())])
    assert (await adapter.submit("local-operation-1")).state is WriteState.COMPLETED
    assert len(transport.requests) == 1
    real_transport = VietShareHttpTransport()
    with pytest.raises(Exception, match="empty-body GET only"):
        await real_transport.send(transport.requests[0], timeout_seconds=1)
    await real_transport.aclose()
