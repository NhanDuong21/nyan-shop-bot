"""Disposable PostgreSQL and injected fake supplier transport only."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator, Callable

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from nyan_shop_bot.suppliers.vietshare.capped_runtime import (
    CappedRuntimeError,
    CappedTestPlan,
    VietShareCappedTestRuntime,
)
from nyan_shop_bot.suppliers.vietshare.models import (
    ProductDetailSuccess,
    VietShareCredentials,
    VietShareProduct,
    VietShareRequest,
    VietShareResponse,
    VndMoney,
)
from nyan_shop_bot.suppliers.vietshare.pg_gate import GateError, GateState, VietSharePgGate
from nyan_shop_bot.suppliers.vietshare.secret_delivery import (
    SecretDeliveryError,
    VietShareSecretDeliveryStore,
)
from tests.integration.orders.support import (
    DISPOSABLE_ORDER_DATABASE_URL,
    require_disposable_order_database_url,
)

pytestmark = pytest.mark.integration
OPERATOR = "unix-uid:4242"
SECRET_MARKER = "synthetic-account-material-never-log"
APPROVAL_REF = "sha256:" + "a" * 64
EVIDENCE_REF = "sha256:" + "b" * 64


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = require_disposable_order_database_url(
        os.environ.get("DATABASE_URL", DISPOSABLE_ORDER_DATABASE_URL)
    )
    database = create_async_engine(url, hide_parameters=True)

    async def reset() -> None:
        async with database.begin() as connection:
            await connection.execute(
                text("""
                TRUNCATE vietshare_secret_deliveries, vietshare_recovery_events,
                    vietshare_write_auth_attempts, vietshare_write_journal,
                    vietshare_write_gate_events
            """)
            )
            await connection.execute(
                text("""
                UPDATE vietshare_write_gate_control SET enabled=false,
                    allowed_operator_ids=ARRAY[]::varchar[], approved_test_id=NULL,
                    approved_product_id=NULL, approved_quantity=NULL,
                    approved_max_unit_price_vnd=NULL, approved_spend_cap_vnd=NULL,
                    approved_wallet_id=NULL, approved_currency=NULL,
                    approved_by=NULL, approval_ref=NULL WHERE id=1
            """)
            )
            await connection.execute(text("TRUNCATE vietshare_write_gate_events"))

    await reset()
    try:
        yield database
    finally:
        await reset()
        await database.dispose()


def plan(test_id: str = "synthetic-product-28") -> CappedTestPlan:
    return CappedTestPlan(test_id, 28, 1, 5_000, 5_000, "synthetic-vnd-wallet", OPERATOR)


class FakeOperator:
    def __init__(self, identity: str = OPERATOR) -> None:
        self.identity = identity

    def current_id(self) -> str:
        return self.identity


class FakeReader:
    def __init__(self, *, stock: int = 4, price: int = 4_000) -> None:
        self.stock = stock
        self.price = price
        self.calls = 0

    async def get_product(self, product_id: int) -> ProductDetailSuccess:
        self.calls += 1
        assert product_id == 28
        return ProductDetailSuccess(
            value=VietShareProduct(
                id=28,
                name="Synthetic product 28",
                description="No customer input required.",
                price=VndMoney(self.price),
                flash_sale_id=None,
                stock=self.stock,
                allow_quantity=False,
                max_quantity=1,
                currencies=("VND",),
                price_usd="0.2",
            ),
            attempts=1,
        )


def completed(request: VietShareRequest, *, total: int = 4_000) -> VietShareResponse:
    body = json.dumps(
        {
            "success": True,
            "order": {
                "order_code": "SYNTHETIC-ORDER-28",
                "status": "completed",
                "channel": "api",
                "product": {"id": 28, "name": "Synthetic product 28"},
                "quantity": 1,
                "unit_price": 4_000,
                "unit_prices": [4_000],
                "price_breakdown": [{"quantity": 1, "unit_price": 4_000, "subtotal": 4_000}],
                "total_amount": total,
                "discount_amount": 0,
                "accounts": [SECRET_MARKER],
                "idempotency_key": request.headers["Idempotency-Key"],
                "created_at": "2026-09-25T00:00:00+00:00",
                "delivered_at": "2026-09-25T00:00:00+00:00",
            },
        },
        separators=(",", ":"),
    ).encode()
    return VietShareResponse(status_code=200, body=body)


class FakeTransport:
    def __init__(
        self,
        responses: list[
            VietShareResponse | Exception | Callable[[VietShareRequest], VietShareResponse]
        ],
    ) -> None:
        self.responses = iter(responses)
        self.requests: list[VietShareRequest] = []

    async def send(self, request: VietShareRequest, *, timeout_seconds: float) -> VietShareResponse:
        assert timeout_seconds == 5
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response(request) if callable(response) else response


def runtime(
    engine: AsyncEngine,
    transport: FakeTransport,
    *,
    enabled: bool,
    operator: FakeOperator | None = None,
    reader: FakeReader | None = None,
    key: bytes | None = None,
) -> VietShareCappedTestRuntime:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    values = iter((1000, 1001, 1002, 1003))
    nonces = iter(("synthetic-nonce-0001", "synthetic-nonce-0002"))
    return VietShareCappedTestRuntime(
        gate=VietSharePgGate(sessions),
        delivery_store=VietShareSecretDeliveryStore(sessions, key=key or Fernet.generate_key()),
        credentials=VietShareCredentials("synthetic-id", "synthetic-secret"),
        transport=transport,
        product_reader=reader or FakeReader(),
        operator=operator or FakeOperator(),
        kill_switch_enabled=enabled,
        clock=lambda: next(values),
        nonce_source=lambda: next(nonces),
    )


async def test_operator_binding_exact_arm_and_encrypted_delivery(engine: AsyncEngine) -> None:
    transport = FakeTransport([completed])
    key = Fernet.generate_key()
    service = runtime(engine, transport, enabled=False, key=key)
    with pytest.raises(CappedRuntimeError, match="operator"):
        await runtime(
            engine, transport, enabled=False, operator=FakeOperator("unix-uid:9999"), key=key
        ).prepare(plan())
    await service.prepare(plan())
    await service.prepare(plan())
    with pytest.raises(CappedRuntimeError, match="OFF"):
        await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    with pytest.raises(CappedRuntimeError, match="OFF"):
        await service.dispatch(plan().test_id)
    live = runtime(engine, transport, enabled=True, key=key)
    with pytest.raises(GateError, match="tuple"):
        await live.arm(
            CappedTestPlan(plan().test_id, 28, 1, 6_000, 6_000, "synthetic-vnd-wallet", OPERATOR),
            approved_by="synthetic-owner",
            approval_ref=APPROVAL_REF,
        )
    await live.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    with pytest.raises(CappedRuntimeError, match="eligible"):
        await runtime(
            engine, transport, enabled=True, operator=FakeOperator("unix-uid:9999"), key=key
        ).dispatch(plan().test_id)
    result = await live.dispatch(plan().test_id)
    assert result.state is GateState.SUCCEEDED
    assert len(transport.requests) == 1
    with pytest.raises(CappedRuntimeError, match="eligible"):
        await live.dispatch(plan().test_id)
    assert len(transport.requests) == 1
    second_plan = plan("synthetic-second-test")
    await live.prepare(second_plan)
    with pytest.raises(GateError, match="completed"):
        await live.arm(second_plan, approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert (
        transport.requests[0].body
        == b'{"product_id":28,"quantity":1,"max_unit_price":5000,"currency":"VND"}'
    )
    sent = transport.requests[0]
    canonical = (
        f"{sent.headers['X-Timestamp']}|{sent.headers['X-Nonce']}|POST|/v1/orders|"
        f"{hashlib.sha256(sent.body).hexdigest()}"
    ).encode()
    assert (
        sent.headers["X-Signature"]
        == hmac.new(b"synthetic-secret", canonical, hashlib.sha256).hexdigest()
    )
    gate = VietSharePgGate(async_sessionmaker(engine))
    record = await gate.get(plan().test_id)
    assert record is not None and record.secret_delivery_ref is not None
    assert record.supplier_order_code == "SYNTHETIC-ORDER-28"
    assert SECRET_MARKER not in repr(record) + repr(result) + repr(live)
    async with engine.connect() as connection:
        ciphertext = await connection.scalar(
            text("SELECT ciphertext FROM vietshare_secret_deliveries WHERE test_id=:id"),
            {"id": plan().test_id},
        )
        assert ciphertext is not None and SECRET_MARKER.encode() not in bytes(ciphertext)
        assert (
            await connection.scalar(
                text("SELECT enabled FROM vietshare_write_gate_control WHERE id=1")
            )
            is False
        )
    with pytest.raises(SecretDeliveryError):
        await runtime(
            engine, transport, enabled=False, operator=FakeOperator("unix-uid:9999"), key=key
        ).read_delivery(record.secret_delivery_ref)
    delivery = await live.read_delivery(record.secret_delivery_ref)
    assert delivery.accounts.values == (SECRET_MARKER,)
    assert SECRET_MARKER not in repr(delivery)
    await live.acknowledge_delivery(record.secret_delivery_ref)
    with pytest.raises(SecretDeliveryError):
        await live.read_delivery(record.secret_delivery_ref)


@pytest.mark.parametrize(
    "pending",
    [
        VietShareResponse(status_code=202, headers={"Retry-After": "0"}, body=b"{}"),
        VietShareResponse(
            status_code=409,
            headers={"Retry-After": "0"},
            body=b'{"detail":{"code":"REQUEST_IN_PROGRESS"}}',
        ),
    ],
)
async def test_pending_freezes_new_key_and_recovery_reuses_exact_body(
    engine: AsyncEngine, pending: VietShareResponse
) -> None:
    transport = FakeTransport(
        [
            pending,
            completed,
        ]
    )
    reader = FakeReader()
    key = Fernet.generate_key()
    service = runtime(engine, transport, enabled=True, reader=reader, key=key)
    await service.prepare(plan())
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert (await service.dispatch(plan().test_id)).state is GateState.RECONCILING
    assert reader.calls == 1
    other = plan("synthetic-other")
    await service.prepare(other)
    with pytest.raises(GateError, match="unresolved"):
        await service.arm(other, approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    reader.stock = 0
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert (await service.dispatch(plan().test_id)).state is GateState.SUCCEEDED
    assert reader.calls == 1  # Recovery never rejects a known obligation on changed stock.
    first, second = transport.requests
    assert first.body == second.body
    assert first.headers["Idempotency-Key"] == second.headers["Idempotency-Key"]
    assert first.headers["X-Timestamp"] != second.headers["X-Timestamp"]
    assert first.headers["X-Nonce"] != second.headers["X-Nonce"]
    assert first.headers["X-Signature"] != second.headers["X-Signature"]
    assert (
        hashlib.sha256(first.body).hexdigest()
        == (await VietSharePgGate(async_sessionmaker(engine)).get(plan().test_id)).body_sha256
    )


async def test_timeout_requires_manual_reconciliation_and_mismatch_stays_frozen(
    engine: AsyncEngine,
) -> None:
    transport = FakeTransport(
        [
            TimeoutError("synthetic timeout"),
            VietShareResponse(status_code=409, body=b'{"detail":{"code":"IDEMPOTENCY_MISMATCH"}}'),
        ]
    )
    service = runtime(engine, transport, enabled=True)
    await service.prepare(plan())
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert (await service.dispatch(plan().test_id)).state is GateState.UNKNOWN
    with pytest.raises(GateError, match="state"):
        await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    await service.mark_reconciling(plan().test_id, evidence_ref=EVIDENCE_REF)
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    result = await service.dispatch(plan().test_id)
    assert result.state is GateState.RECONCILING
    assert result.error_code == "IDEMPOTENCY_MISMATCH"
    with pytest.raises(GateError, match="frozen"):
        await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert len(transport.requests) == 2
    assert transport.requests[0].body == transport.requests[1].body
    assert (
        transport.requests[0].headers["Idempotency-Key"]
        == transport.requests[1].headers["Idempotency-Key"]
    )


async def test_over_cap_preserves_secret_for_reconciliation(engine: AsyncEngine) -> None:
    transport = FakeTransport([lambda request: completed(request, total=6_000)])
    key = Fernet.generate_key()
    service = runtime(engine, transport, enabled=True, key=key)
    await service.prepare(plan())
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert (await service.dispatch(plan().test_id)).state is GateState.RECONCILING
    record = await VietSharePgGate(async_sessionmaker(engine)).get(plan().test_id)
    assert record is not None and record.secret_delivery_ref is not None
    assert record.last_error_code == "SPEND_CAP_EXCEEDED"
    delivery = await service.read_delivery(record.secret_delivery_ref)
    assert delivery.accounts.values == (SECRET_MARKER,)
    with pytest.raises(GateError, match="frozen"):
        await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)


async def test_lost_dispatch_requires_operator_attestation_and_same_key_recovery(
    engine: AsyncEngine,
) -> None:
    transport = FakeTransport([completed])
    service = runtime(engine, transport, enabled=True)
    await service.prepare(plan())
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    gate = VietSharePgGate(async_sessionmaker(engine))
    claimed = await gate.claim(
        test_id=plan().test_id,
        operator_id=OPERATOR,
        timestamp=999,
        nonce="synthetic-lost-nonce",
    )
    with pytest.raises(GateError, match="evidence"):
        await service.mark_dispatch_lost(plan().test_id, evidence_ref="")
    assert (await gate.get(plan().test_id)).state is GateState.DISPATCHING
    await service.mark_dispatch_lost(plan().test_id, evidence_ref=EVIDENCE_REF)
    unknown = await gate.get(plan().test_id)
    assert unknown is not None and unknown.state is GateState.UNKNOWN
    assert unknown.idempotency_key == claimed.idempotency_key
    with pytest.raises(GateError, match="state"):
        await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    await service.mark_reconciling(plan().test_id, evidence_ref=EVIDENCE_REF)
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert (await service.dispatch(plan().test_id)).state is GateState.SUCCEEDED
    assert transport.requests[0].headers["Idempotency-Key"] == claimed.idempotency_key
    assert transport.requests[0].body == claimed.raw_body
    async with engine.connect() as connection:
        actions = (
            (
                await connection.execute(
                    text("""
                SELECT action FROM vietshare_recovery_events
                WHERE test_id=:id ORDER BY event_id
            """),
                    {"id": plan().test_id},
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["DISPATCH_LOST", "UNKNOWN_TO_RECONCILING"]


async def test_secret_store_failure_never_claims_supplier_success(engine: AsyncEngine) -> None:
    class BrokenStore:
        async def put(self, **_kwargs: object) -> str:
            raise RuntimeError("synthetic-private-storage-error")

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    transport = FakeTransport([completed])
    service = VietShareCappedTestRuntime(
        gate=VietSharePgGate(sessions),
        delivery_store=BrokenStore(),  # type: ignore[arg-type]
        credentials=VietShareCredentials("synthetic-id", "synthetic-secret"),
        transport=transport,
        product_reader=FakeReader(),
        operator=FakeOperator(),
        kill_switch_enabled=True,
        clock=lambda: 1000,
        nonce_source=lambda: "synthetic-nonce-0001",
    )
    await service.prepare(plan())
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    outcome = await service.dispatch(plan().test_id)
    assert outcome.state is GateState.RECONCILING
    record = await VietSharePgGate(sessions).get(plan().test_id)
    assert record is not None
    assert record.secret_delivery_ref is None
    assert record.supplier_order_code == "SYNTHETIC-ORDER-28"
    assert record.last_error_code == "SECRET_DELIVERY_UNAVAILABLE"
    assert "synthetic-private-storage-error" not in repr(outcome) + repr(record)


async def test_expired_delivery_cannot_be_read_and_can_be_purged_without_key(
    engine: AsyncEngine,
) -> None:
    key = Fernet.generate_key()
    service = runtime(engine, FakeTransport([completed]), enabled=True, key=key)
    await service.prepare(plan())
    await service.arm(plan(), approved_by="synthetic-owner", approval_ref=APPROVAL_REF)
    assert (await service.dispatch(plan().test_id)).state is GateState.SUCCEEDED
    sessions = async_sessionmaker(engine)
    record = await VietSharePgGate(sessions).get(plan().test_id)
    assert record is not None and record.secret_delivery_ref is not None
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            UPDATE vietshare_secret_deliveries
            SET created_at=clock_timestamp() - INTERVAL '2 hours',
                expires_at=clock_timestamp() - INTERVAL '1 hour'
            WHERE test_id=:id
        """),
            {"id": plan().test_id},
        )
    with pytest.raises(SecretDeliveryError):
        await service.read_delivery(record.secret_delivery_ref)
    assert await VietShareSecretDeliveryStore.purge_expired_rows(sessions) == 1
