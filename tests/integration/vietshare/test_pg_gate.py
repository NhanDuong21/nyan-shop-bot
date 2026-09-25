"""Disposable PostgreSQL and injected fake transport only; no supplier network."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator, Iterable

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from nyan_shop_bot.suppliers.vietshare.models import (
    VietShareCredentials,
    VietShareRequest,
    VietShareResponse,
)
from nyan_shop_bot.suppliers.vietshare.pg_gate import (
    CappedTestIntent,
    GateError,
    GateState,
    VietSharePgGate,
    VietSharePgOfflineExecutor,
)
from nyan_shop_bot.suppliers.vietshare.write_orders import OrderPurchase
from tests.integration.orders.support import (
    DISPOSABLE_ORDER_DATABASE_URL,
    require_disposable_order_database_url,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = require_disposable_order_database_url(
        os.environ.get("DATABASE_URL", DISPOSABLE_ORDER_DATABASE_URL)
    )
    db = create_async_engine(url, hide_parameters=True)
    async with db.begin() as connection:
        await connection.execute(
            text("""
            TRUNCATE vietshare_write_auth_attempts, vietshare_write_journal
        """)
        )
        await connection.execute(
            text("""
            UPDATE vietshare_write_gate_control SET enabled=false,
                allowed_operator_ids=ARRAY[]::varchar[], approved_test_id=NULL,
                approved_product_id=NULL, approved_quantity=NULL,
                approved_max_unit_price_vnd=NULL, approved_spend_cap_vnd=NULL,
                approved_wallet_id=NULL, approved_currency=NULL WHERE id=1
        """)
        )
    try:
        yield db
    finally:
        async with db.begin() as connection:
            await connection.execute(
                text("""
                TRUNCATE vietshare_write_auth_attempts, vietshare_write_journal
            """)
            )
            await connection.execute(
                text("""
                UPDATE vietshare_write_gate_control SET enabled=false,
                    allowed_operator_ids=ARRAY[]::varchar[], approved_test_id=NULL,
                    approved_product_id=NULL, approved_quantity=NULL,
                    approved_max_unit_price_vnd=NULL, approved_spend_cap_vnd=NULL,
                    approved_wallet_id=NULL, approved_currency=NULL WHERE id=1
            """)
            )
        await db.dispose()


@pytest.fixture
def gate(engine: AsyncEngine) -> VietSharePgGate:
    return VietSharePgGate(async_sessionmaker(engine, expire_on_commit=False))


def intent(
    *,
    test_id: str = "synthetic-test-one",
    key: str = "synthetic-key-one",
    price: int = 20_000,
    cap: int = 20_000,
) -> CappedTestIntent:
    return CappedTestIntent(
        test_id=test_id,
        idempotency_key=key,
        purchase=OrderPurchase(7, 1, price, "VND"),
        absolute_spend_cap_vnd=cap,
        wallet_id="synthetic-vnd-wallet",
        operator_id="synthetic-operator",
    )


async def arm(engine: AsyncEngine, test_id: str = "synthetic-test-one") -> None:
    """A test transaction simulates a later separately approved owner decision."""
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            UPDATE vietshare_write_gate_control SET enabled=true,
                allowed_operator_ids=ARRAY['synthetic-operator']::varchar[],
                approved_test_id=:id, approved_product_id=7, approved_quantity=1,
                approved_max_unit_price_vnd=20000, approved_spend_cap_vnd=20000,
                approved_wallet_id='synthetic-vnd-wallet', approved_currency='VND'
            WHERE id=1
        """),
            {"id": test_id},
        )


class FakeTransport:
    def __init__(self, outcomes: Iterable[VietShareResponse | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.requests: list[VietShareRequest] = []
        self.gate: VietSharePgGate | None = None
        self.observed_states: list[GateState] = []

    async def send(self, request: VietShareRequest, *, timeout_seconds: float) -> VietShareResponse:
        self.requests.append(request)
        if self.gate is not None:
            record = await self.gate.get("synthetic-test-one")
            assert record is not None
            self.observed_states.append(record.state)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def executor(
    gate: VietSharePgGate,
    transport: FakeTransport,
    *,
    timestamps: tuple[int, ...] = (1000, 1001, 1002, 1003),
) -> VietSharePgOfflineExecutor:
    transport.gate = gate
    clock_values = iter(timestamps)
    nonces = iter(
        (
            "synthetic-nonce-0001",
            "synthetic-nonce-0002",
            "synthetic-nonce-0003",
            "synthetic-nonce-0004",
        )
    )
    return VietSharePgOfflineExecutor(
        gate=gate,
        credentials=VietShareCredentials("synthetic-id", "synthetic-secret"),
        transport=transport,
        clock=lambda: next(clock_values),
        nonce_source=lambda: next(nonces),
    )


def completed_body(*, total: int = 20_000, account: str = "private-delivery-marker") -> bytes:
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
                "total_amount": total,
                "discount_amount": 0,
                "accounts": [account],
                "idempotency_key": "synthetic-key-one",
                "created_at": "2026-09-25T00:00:00+00:00",
                "delivered_at": "2026-09-25T00:00:00+00:00",
            },
        },
        separators=(",", ":"),
    ).encode()


async def control_enabled(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        return bool(
            await connection.scalar(
                text("SELECT enabled FROM vietshare_write_gate_control WHERE id=1")
            )
        )


async def auth_count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return int(
            await connection.scalar(text("SELECT count(*) FROM vietshare_write_auth_attempts"))
        )


async def test_prepare_is_durable_immutable_and_defaults_off(
    gate: VietSharePgGate,
    engine: AsyncEngine,
) -> None:
    original = intent()
    saved = await gate.prepare(original)
    assert saved.state is GateState.PREPARED
    assert saved.raw_body == original.purchase.raw_body()
    assert saved.body_sha256 == hashlib.sha256(saved.raw_body).hexdigest()
    assert saved.absolute_spend_cap_vnd == 20_000
    assert not await control_enabled(engine)
    assert await gate.prepare(original) == saved
    with pytest.raises(GateError, match="conflict"):
        await gate.prepare(intent(price=19_000))
    with pytest.raises(GateError, match="conflict"):
        await gate.prepare(intent(test_id="synthetic-test-two"))
    with pytest.raises(GateError, match="disabled"):
        await gate.claim(
            test_id=original.test_id,
            operator_id=original.operator_id,
            timestamp=1000,
            nonce="synthetic-nonce-0001",
        )
    assert await auth_count(engine) == 0
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(Exception, match="immutable"):
                await connection.execute(
                    text("""
                    UPDATE vietshare_write_journal SET raw_body='changed'
                    WHERE test_id='synthetic-test-one'
                """)
                )
        finally:
            await transaction.rollback()


async def test_exact_match_allowlist_cap_and_concurrent_claim(
    gate: VietSharePgGate,
    engine: AsyncEngine,
) -> None:
    await gate.prepare(intent())
    await arm(engine)
    with pytest.raises(GateError, match="approval"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="other-operator",
            timestamp=1000,
            nonce="synthetic-nonce-0000",
        )
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            UPDATE vietshare_write_gate_control SET approved_product_id=8 WHERE id=1
        """)
        )
    with pytest.raises(GateError, match="approval"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1000,
            nonce="synthetic-nonce-0000",
        )
    await arm(engine)
    results = await asyncio.gather(
        gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1000,
            nonce="synthetic-nonce-0001",
        ),
        gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1001,
            nonce="synthetic-nonce-0002",
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(item, GateError) for item in results) == 1
    assert (
        sum(isinstance(item, object) and not isinstance(item, Exception) for item in results) == 1
    )
    assert (await gate.get("synthetic-test-one")).state is GateState.DISPATCHING  # type: ignore[union-attr]
    assert await auth_count(engine) == 1
    with pytest.raises(GateError, match="state"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1002,
            nonce="synthetic-nonce-0003",
        )


async def test_success_hmac_and_no_delivery_material_in_journal(
    gate: VietSharePgGate,
    engine: AsyncEngine,
) -> None:
    saved = await gate.prepare(intent())
    await arm(engine)
    transport = FakeTransport([VietShareResponse(200, body=completed_body())])
    result = await executor(gate, transport).submit(
        "synthetic-test-one", operator_id="synthetic-operator"
    )
    assert result.state is GateState.SUCCEEDED
    assert transport.observed_states == [GateState.DISPATCHING]
    request = transport.requests[0]
    assert request.method == "POST" and request.path_with_query == "/v1/orders"
    assert request.body == saved.raw_body
    assert request.headers["Idempotency-Key"] == saved.idempotency_key
    canonical = f"1000|synthetic-nonce-0001|POST|/v1/orders|{saved.body_sha256}".encode()
    assert (
        request.headers["X-Signature"]
        == hmac.new(b"synthetic-secret", canonical, hashlib.sha256).hexdigest()
    )
    assert not await control_enabled(engine)
    assert await auth_count(engine) == 1
    record = await gate.get("synthetic-test-one")
    assert record is not None and record.state is GateState.SUCCEEDED
    assert "private-delivery-marker" not in repr(record)
    assert "private-delivery-marker" not in repr(result)
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("""
            SELECT raw_body, supplier_order_code, last_error_code
            FROM vietshare_write_journal WHERE test_id='synthetic-test-one'
        """)
            )
        ).one()
    assert b"private-delivery-marker" not in bytes(row.raw_body)
    assert row.supplier_order_code == "SYNTHETIC-ORDER-1"
    assert row.last_error_code is None


@pytest.mark.parametrize(
    "response",
    [
        VietShareResponse(202, headers={"Retry-After": "7"}),
        VietShareResponse(
            409,
            headers={"Retry-After": "7"},
            body=(b'{"detail":{"code":"REQUEST_IN_PROGRESS","message":"private"}}'),
        ),
    ],
)
async def test_202_or_request_in_progress_freezes_new_key_until_recovery(
    gate: VietSharePgGate,
    engine: AsyncEngine,
    response: VietShareResponse,
) -> None:
    saved = await gate.prepare(intent())
    await arm(engine)
    transport = FakeTransport([response, VietShareResponse(200, body=completed_body())])
    worker = executor(gate, transport, timestamps=(1000, 1001, 1008, 1009))
    first = await worker.submit("synthetic-test-one", operator_id="synthetic-operator")
    assert first.state is GateState.RECONCILING
    assert first.retry_after_seconds == 7.0
    assert not await control_enabled(engine)
    assert (await gate.get(saved.test_id)).retry_not_before is not None  # type: ignore[union-attr]
    await gate.prepare(intent(test_id="synthetic-test-two", key="synthetic-key-two"))
    await arm(engine, "synthetic-test-two")
    with pytest.raises(GateError, match="unresolved"):
        await gate.claim(
            test_id="synthetic-test-two",
            operator_id="synthetic-operator",
            timestamp=1008,
            nonce="synthetic-nonce-0003",
        )
    await arm(engine)
    with pytest.raises(GateError, match="Retry-After"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1007,
            nonce="synthetic-nonce-0003",
        )
    second = await worker.submit("synthetic-test-one", operator_id="synthetic-operator")
    assert second.state is GateState.SUCCEEDED
    assert len(transport.requests) == 2
    assert transport.requests[0].body == transport.requests[1].body == saved.raw_body
    assert (
        transport.requests[0].headers["Idempotency-Key"]
        == transport.requests[1].headers["Idempotency-Key"]
        == saved.idempotency_key
    )
    for name in ("X-Timestamp", "X-Nonce", "X-Signature"):
        assert transport.requests[0].headers[name] != transport.requests[1].headers[name]


@pytest.mark.parametrize(
    "uncertain",
    [
        TimeoutError("private timeout marker"),
        VietShareResponse(502, body=b"private gateway marker"),
    ],
)
async def test_uncertain_and_mismatch_fail_closed(
    gate: VietSharePgGate,
    engine: AsyncEngine,
    uncertain: VietShareResponse | Exception,
) -> None:
    await gate.prepare(intent())
    await arm(engine)
    transport = FakeTransport([uncertain])
    result = await executor(gate, transport).submit(
        "synthetic-test-one", operator_id="synthetic-operator"
    )
    assert result.state is GateState.UNKNOWN
    assert "private timeout marker" not in repr(result)
    assert not await control_enabled(engine)
    await gate.prepare(intent(test_id="synthetic-test-two", key="synthetic-key-two"))
    await arm(engine, "synthetic-test-two")
    with pytest.raises(GateError, match="unresolved"):
        await gate.claim(
            test_id="synthetic-test-two",
            operator_id="synthetic-operator",
            timestamp=1001,
            nonce="synthetic-nonce-0002",
        )
    await gate.mark_reconciling("synthetic-test-one", operator_id="synthetic-operator")
    await arm(engine)
    mismatch = FakeTransport(
        [
            VietShareResponse(
                409,
                body=b'{"detail":{"code":"IDEMPOTENCY_MISMATCH","message":"private"}}',
            )
        ]
    )
    failed = await VietSharePgOfflineExecutor(
        gate=gate,
        credentials=VietShareCredentials("synthetic-id", "synthetic-secret"),
        transport=mismatch,
        clock=iter((1002, 1003)).__next__,
        nonce_source=lambda: "synthetic-nonce-0002",
    ).submit("synthetic-test-one", operator_id="synthetic-operator")
    assert failed.state is GateState.RECONCILING
    assert failed.error_code == "IDEMPOTENCY_MISMATCH"
    await arm(engine)
    with pytest.raises(GateError, match="frozen"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1004,
            nonce="synthetic-nonce-0004",
        )
    assert await auth_count(engine) == 2


async def test_database_rejects_incomplete_arm_and_reused_auth(
    gate: VietSharePgGate,
    engine: AsyncEngine,
) -> None:
    await gate.prepare(intent())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text("""
                    UPDATE vietshare_write_gate_control SET enabled=true WHERE id=1
                """)
                )
        finally:
            await transaction.rollback()
    await arm(engine)
    await gate.claim(
        test_id="synthetic-test-one",
        operator_id="synthetic-operator",
        timestamp=1000,
        nonce="synthetic-nonce-0001",
    )
    await gate.finish("synthetic-test-one", GateState.RECONCILING)
    await arm(engine)
    with pytest.raises(GateError, match="previously used"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1000,
            nonce="synthetic-nonce-0002",
        )
    with pytest.raises(GateError, match="previously used"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1001,
            nonce="synthetic-nonce-0001",
        )
    assert await auth_count(engine) == 1


async def test_database_unique_index_rejects_second_unresolved_dispatch(
    gate: VietSharePgGate,
    engine: AsyncEngine,
) -> None:
    await gate.prepare(intent())
    await gate.prepare(intent(test_id="synthetic-test-two", key="synthetic-key-two"))
    await arm(engine)
    await gate.claim(
        test_id="synthetic-test-one",
        operator_id="synthetic-operator",
        timestamp=1000,
        nonce="synthetic-nonce-0001",
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text("""
                    UPDATE vietshare_write_journal SET state='DISPATCHING'
                    WHERE test_id='synthetic-test-two'
                """)
                )
        finally:
            await transaction.rollback()


async def test_spend_cap_violation_is_not_called_success(
    gate: VietSharePgGate,
    engine: AsyncEngine,
) -> None:
    await gate.prepare(intent())
    await arm(engine)
    result = await executor(
        gate, FakeTransport([VietShareResponse(200, body=completed_body(total=20_001))])
    ).submit("synthetic-test-one", operator_id="synthetic-operator")
    assert result.state is GateState.RECONCILING
    assert result.error_code == "SPEND_CAP_EXCEEDED"
    assert not await control_enabled(engine)
    await arm(engine)
    with pytest.raises(GateError, match="frozen"):
        await gate.claim(
            test_id="synthetic-test-one",
            operator_id="synthetic-operator",
            timestamp=1002,
            nonce="synthetic-nonce-0002",
        )
