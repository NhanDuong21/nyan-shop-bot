"""Offline-only PostgreSQL obligation gate for one capped VietShare test.

Nothing in the application runtime imports or arms this gate. Its only outbound
boundary is an injected transport, used by the conformance tests with a fake.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nyan_shop_bot.suppliers.vietshare.models import (
    SensitiveHeaders,
    VietShareCredentials,
    VietShareRequest,
    VietShareResponse,
)
from nyan_shop_bot.suppliers.vietshare.write_orders import (
    FakeOnlyTransport,
    OrderPurchase,
    WriteContractError,
    _error_code,
    _retry_after,
    parse_order_response,
)

_KEY = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_MAX_BIGINT = (1 << 63) - 1
_PATH = "/v1/orders"


def _canonical_bytes(timestamp: int, nonce: str, body_sha256: str) -> bytes:
    return f"{timestamp}|{nonce}|POST|{_PATH}|{body_sha256}".encode()


class GateError(ValueError):
    """A fail-closed error that never includes inputs or supplier material."""


class GateState(StrEnum):
    PREPARED = "PREPARED"
    DISPATCHING = "DISPATCHING"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_SAFE = "FAILED_SAFE"


@dataclass(frozen=True, repr=False)
class CappedTestIntent:
    test_id: str
    idempotency_key: str = field(repr=False)
    purchase: OrderPurchase = field(repr=False)
    absolute_spend_cap_vnd: int
    wallet_id: str = field(repr=False)
    operator_id: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.test_id) is not str
            or not 1 <= len(self.test_id) <= 64
            or _ID.fullmatch(self.test_id) is None
            or type(self.idempotency_key) is not str
            or _KEY.fullmatch(self.idempotency_key) is None
            or not isinstance(self.purchase, OrderPurchase)
            or self.purchase.currency != "VND"
            or type(self.absolute_spend_cap_vnd) is not int
            or not 0 < self.absolute_spend_cap_vnd <= _MAX_BIGINT
            or self.purchase.max_unit_price > _MAX_BIGINT
            or self.purchase.quantity * self.purchase.max_unit_price > self.absolute_spend_cap_vnd
            or self.purchase.supplier_emails
            or self.purchase.coupon_code is not None
            or self.purchase.flash_sale_id is not None
            or type(self.wallet_id) is not str
            or _ID.fullmatch(self.wallet_id) is None
            or type(self.operator_id) is not str
            or _ID.fullmatch(self.operator_id) is None
        ):
            raise GateError("Invalid capped VietShare test intent")

    def __repr__(self) -> str:
        return "CappedTestIntent(<redacted>)"


@dataclass(frozen=True, repr=False)
class GateRecord:
    test_id: str
    idempotency_key: str = field(repr=False)
    raw_body: bytes = field(repr=False)
    body_sha256: str
    product_id: int
    quantity: int
    max_unit_price_vnd: int
    absolute_spend_cap_vnd: int
    wallet_id: str = field(repr=False)
    operator_id: str = field(repr=False)
    state: GateState
    retry_not_before: datetime | None = None
    supplier_order_code: str | None = field(default=None, repr=False)
    last_error_code: str | None = None

    def __repr__(self) -> str:
        return f"GateRecord(state={self.state.value}, details=<redacted>)"


@dataclass(frozen=True, repr=False)
class GateOutcome:
    state: GateState
    retry_after_seconds: float | None = None
    error_code: str | None = None

    def __repr__(self) -> str:
        return f"GateOutcome(state={self.state.value}, details=<redacted>)"


_RECORD_COLUMNS = """
    test_id, idempotency_key, raw_body, body_sha256, product_id, quantity,
    max_unit_price_vnd, absolute_spend_cap_vnd, wallet_id, operator_id,
    state, retry_not_before, supplier_order_code, last_error_code
"""


def _record(row: object) -> GateRecord:
    # SQLAlchemy RowMapping is duck typed; no supplier payload is formatted here.
    values = dict(row)  # type: ignore[call-overload]
    return GateRecord(
        test_id=values["test_id"],
        idempotency_key=values["idempotency_key"],
        raw_body=bytes(values["raw_body"]),
        body_sha256=values["body_sha256"],
        product_id=values["product_id"],
        quantity=values["quantity"],
        max_unit_price_vnd=values["max_unit_price_vnd"],
        absolute_spend_cap_vnd=values["absolute_spend_cap_vnd"],
        wallet_id=values["wallet_id"],
        operator_id=values["operator_id"],
        state=GateState(values["state"]),
        retry_not_before=values["retry_not_before"],
        supplier_order_code=values["supplier_order_code"],
        last_error_code=values["last_error_code"],
    )


class VietSharePgGate:
    """Serializes every claim on the singleton control row before dispatch."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    def __repr__(self) -> str:
        return "VietSharePgGate(<redacted>)"

    async def get(self, test_id: str) -> GateRecord | None:
        async with self._sessions() as session:
            result = await session.execute(
                text(f"SELECT {_RECORD_COLUMNS} FROM vietshare_write_journal WHERE test_id = :id"),
                {"id": test_id},
            )
            row = result.mappings().one_or_none()
            return _record(row) if row is not None else None

    async def server_now_seconds(self) -> float:
        async with self._sessions() as session:
            value = await session.scalar(text("SELECT clock_timestamp()"))
            if not isinstance(value, datetime):
                raise GateError("Database clock is unavailable")
            return value.timestamp()

    async def prepare(self, intent: CappedTestIntent) -> GateRecord:
        body = intent.purchase.raw_body()
        digest = hashlib.sha256(body).hexdigest()
        values = {
            "test_id": intent.test_id,
            "key": intent.idempotency_key,
            "body": body,
            "hash": digest,
            "product": intent.purchase.product_id,
            "quantity": intent.purchase.quantity,
            "unit_price": intent.purchase.max_unit_price,
            "cap": intent.absolute_spend_cap_vnd,
            "wallet": intent.wallet_id,
            "operator": intent.operator_id,
        }
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("""
                    INSERT INTO vietshare_write_journal (
                        test_id, idempotency_key, raw_body, body_sha256, source,
                        product_id, quantity, max_unit_price_vnd,
                        absolute_spend_cap_vnd, wallet_id, currency, operator_id, state
                    ) VALUES (
                        :test_id, :key, :body, :hash, 'vietshare', :product, :quantity,
                        :unit_price, :cap, :wallet, 'VND', :operator, 'PREPARED'
                    ) ON CONFLICT DO NOTHING
                """),
                values,
            )
            result = await session.execute(
                text(f"""
                    SELECT {_RECORD_COLUMNS} FROM vietshare_write_journal
                    WHERE test_id = :test_id OR idempotency_key = :key
                    FOR UPDATE
                """),
                values,
            )
            rows = result.mappings().all()
            if len(rows) != 1:
                raise GateError("Test identity or Idempotency-Key conflict")
            record = _record(rows[0])
            if (
                record.test_id != intent.test_id
                or record.idempotency_key != intent.idempotency_key
                or record.raw_body != body
                or record.body_sha256 != digest
                or record.product_id != intent.purchase.product_id
                or record.quantity != intent.purchase.quantity
                or record.max_unit_price_vnd != intent.purchase.max_unit_price
                or record.absolute_spend_cap_vnd != intent.absolute_spend_cap_vnd
                or record.wallet_id != intent.wallet_id
                or record.operator_id != intent.operator_id
            ):
                raise GateError("Test identity or Idempotency-Key conflict")
            return record

    async def claim(
        self,
        *,
        test_id: str,
        operator_id: str,
        timestamp: int,
        nonce: str,
    ) -> GateRecord:
        if (
            type(timestamp) is not int
            or timestamp < 0
            or type(nonce) is not str
            or not 12 <= len(nonce) <= 128
            or "\r" in nonce
            or "\n" in nonce
        ):
            raise GateError("Invalid signing timestamp or nonce")
        async with self._sessions() as session, session.begin():
            control = (
                (
                    await session.execute(
                        text("""
                SELECT enabled, allowed_operator_ids, approved_test_id,
                    approved_product_id, approved_quantity,
                    approved_max_unit_price_vnd, approved_spend_cap_vnd,
                    approved_wallet_id, approved_currency
                FROM vietshare_write_gate_control WHERE id = 1 FOR UPDATE
            """)
                    )
                )
                .mappings()
                .one()
            )
            result = await session.execute(
                text(f"""
                    SELECT {_RECORD_COLUMNS} FROM vietshare_write_journal
                    WHERE test_id=:id FOR UPDATE
                """),
                {"id": test_id},
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise GateError("Test was not durably prepared")
            record = _record(row)
            if (
                not control["enabled"]
                or type(operator_id) is not str
                or operator_id != record.operator_id
                or operator_id not in control["allowed_operator_ids"]
                or control["approved_test_id"] != record.test_id
                or control["approved_product_id"] != record.product_id
                or control["approved_quantity"] != record.quantity
                or control["approved_max_unit_price_vnd"] != record.max_unit_price_vnd
                or control["approved_spend_cap_vnd"] != record.absolute_spend_cap_vnd
                or control["approved_wallet_id"] != record.wallet_id
                or control["approved_currency"] != "VND"
            ):
                raise GateError("VietShare test gate is disabled or approval does not match")
            if record.state not in {GateState.PREPARED, GateState.RECONCILING}:
                raise GateError("Test state does not permit dispatch")
            if record.last_error_code in {
                "IDEMPOTENCY_MISMATCH",
                "SPEND_CAP_EXCEEDED",
            }:
                raise GateError("Supplier result is frozen for reconciliation")
            if hashlib.sha256(record.raw_body).hexdigest() != record.body_sha256:
                raise GateError("Stored request body hash does not match exact bytes")
            expected_body = OrderPurchase(
                product_id=record.product_id,
                quantity=record.quantity,
                max_unit_price=record.max_unit_price_vnd,
                currency="VND",
            ).raw_body()
            if record.raw_body != expected_body:
                raise GateError("Stored request body does not match approved commercial fields")
            now = await session.scalar(text("SELECT clock_timestamp()"))
            if not isinstance(now, datetime):
                raise GateError("Database clock is unavailable")
            if record.retry_not_before is not None and now < record.retry_not_before:
                raise GateError("Retry-After has not elapsed")
            unresolved = await session.scalar(
                text("""
                SELECT test_id FROM vietshare_write_journal
                WHERE source='vietshare' AND test_id<>:id
                    AND state IN ('DISPATCHING','UNKNOWN','RECONCILING')
            """),
                {"id": test_id},
            )
            if unresolved is not None:
                raise GateError("Another VietShare test is unresolved")
            canonical_sha256 = hashlib.sha256(
                _canonical_bytes(timestamp, nonce, record.body_sha256)
            ).hexdigest()
            try:
                await session.execute(
                    text("""
                        INSERT INTO vietshare_write_auth_attempts
                            (nonce, test_id, timestamp, method, body_sha256,
                             canonical_sha256)
                        VALUES (:nonce, :id, :timestamp, 'POST', :hash, :canonical)
                    """),
                    {
                        "nonce": nonce,
                        "id": test_id,
                        "timestamp": timestamp,
                        "hash": record.body_sha256,
                        "canonical": canonical_sha256,
                    },
                )
            except IntegrityError:
                raise GateError("Signing timestamp or nonce was previously used") from None
            await session.execute(
                text("""
                    UPDATE vietshare_write_journal SET state='DISPATCHING',
                        retry_not_before=NULL, updated_at=now()
                    WHERE test_id=:id
                """),
                {"id": test_id},
            )
            return record

    async def finish(
        self,
        test_id: str,
        state: GateState,
        *,
        nonce: str,
        retry_delay_seconds: float | None = None,
        http_status: int | None = None,
        retry_after_header: str | None = None,
        order_code: str | None = None,
        error_code: str | None = None,
    ) -> None:
        if state not in {
            GateState.UNKNOWN,
            GateState.RECONCILING,
            GateState.SUCCEEDED,
        }:
            raise GateError("Invalid automatic completion state")
        if retry_delay_seconds is not None and (
            type(retry_delay_seconds) not in {int, float}
            or not math.isfinite(retry_delay_seconds)
            or not 0 <= retry_delay_seconds <= 1_000_000_000
        ):
            raise GateError("Invalid Retry-After duration")
        if retry_after_header is not None and (
            type(retry_after_header) is not str or len(retry_after_header) > 256
        ):
            raise GateError("Invalid Retry-After evidence")
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("""
                SELECT id FROM vietshare_write_gate_control WHERE id=1 FOR UPDATE
            """)
            )
            result = await session.execute(
                text("""
                UPDATE vietshare_write_journal
                SET state=:state,
                    retry_not_before=CASE WHEN CAST(:delay AS double precision) IS NULL
                        THEN NULL ELSE clock_timestamp() +
                        CAST(:delay AS double precision) * INTERVAL '1 second' END,
                    supplier_order_code=:code,
                    last_error_code=:error, updated_at=now()
                WHERE test_id=:id AND state='DISPATCHING' RETURNING test_id
            """),
                {
                    "id": test_id,
                    "state": state.value,
                    "delay": retry_delay_seconds,
                    "code": order_code,
                    "error": error_code,
                },
            )
            if result.scalar_one_or_none() is None:
                raise GateError("Dispatch state changed before completion")
            attempt = await session.execute(
                text("""
                UPDATE vietshare_write_auth_attempts
                SET http_status=:status, response_code=:error,
                    retry_after_header=:retry_header, outcome_state=:state,
                    completed_at=clock_timestamp()
                WHERE test_id=:id AND nonce=:nonce AND outcome_state IS NULL
                RETURNING nonce
            """),
                {
                    "id": test_id,
                    "nonce": nonce,
                    "status": http_status,
                    "error": error_code,
                    "retry_header": retry_after_header,
                    "state": state.value,
                },
            )
            if attempt.scalar_one_or_none() is None:
                raise GateError("Signing attempt was not reserved before dispatch")
            await session.execute(
                text("""
                UPDATE vietshare_write_gate_control SET enabled=false, updated_at=now()
                WHERE id=1
            """)
            )

    async def mark_reconciling(self, test_id: str, *, operator_id: str) -> None:
        """Record deliberate investigation; this does not authorize a new POST."""
        async with self._sessions() as session, session.begin():
            allowed = await session.scalar(
                text("""
                SELECT allowed_operator_ids FROM vietshare_write_gate_control
                WHERE id=1 FOR UPDATE
            """)
            )
            if type(operator_id) is not str or operator_id not in allowed:
                raise GateError("Operator is not currently allowed to reconcile")
            result = await session.execute(
                text("""
                UPDATE vietshare_write_journal SET state='RECONCILING', updated_at=now()
                WHERE test_id=:id AND operator_id=:operator AND state='UNKNOWN'
                RETURNING test_id
            """),
                {"id": test_id, "operator": operator_id},
            )
            if result.scalar_one_or_none() is None:
                raise GateError("UNKNOWN test and matching operator are required")


class VietSharePgOfflineExecutor:
    """PostgreSQL preflight plus fake transport; never registered in runtime."""

    def __init__(
        self,
        *,
        gate: VietSharePgGate,
        credentials: VietShareCredentials,
        transport: FakeOnlyTransport,
        clock: Callable[[], int],
        nonce_source: Callable[[], str],
        timeout_seconds: float = 5,
    ) -> None:
        self._gate = gate
        self._credentials = credentials
        self._transport = transport
        self._clock = clock
        self._nonce_source = nonce_source
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        return "VietSharePgOfflineExecutor(<redacted>)"

    async def submit(self, test_id: str, *, operator_id: str) -> GateOutcome:
        timestamp = self._clock()
        nonce = self._nonce_source()
        record = await self._gate.claim(
            test_id=test_id,
            operator_id=operator_id,
            timestamp=timestamp,
            nonce=nonce,
        )
        try:
            canonical = _canonical_bytes(timestamp, nonce, record.body_sha256)
            signature = hmac.new(
                self._credentials.secret_bytes,
                canonical,
                hashlib.sha256,
            ).hexdigest()
            request = VietShareRequest(
                method="POST",
                url=f"https://token.vietshare.site{_PATH}",
                path_with_query=_PATH,
                headers=SensitiveHeaders(
                    {
                        "X-Shop-API-ID": self._credentials.api_id,
                        "X-Timestamp": str(timestamp),
                        "X-Nonce": nonce,
                        "X-Signature": signature,
                        "Idempotency-Key": record.idempotency_key,
                        "Content-Type": "application/json",
                    }
                ),
                body=record.raw_body,
            )
            response = await self._transport.send(request, timeout_seconds=self._timeout)
        except Exception:
            await self._gate.finish(
                test_id,
                GateState.UNKNOWN,
                nonce=nonce,
                error_code="TRANSPORT_ERROR",
            )
            return GateOutcome(GateState.UNKNOWN)
        if not isinstance(response, VietShareResponse):
            await self._gate.finish(
                test_id,
                GateState.UNKNOWN,
                nonce=nonce,
                error_code="INVALID_RESPONSE",
            )
            return GateOutcome(GateState.UNKNOWN)
        code = _error_code(response.body)
        received_at = await self._gate.server_now_seconds()
        retry = _retry_after(response.headers, received_at)
        retry_header = next(
            (value for name, value in response.headers.items() if name.casefold() == "retry-after"),
            None,
        )
        if response.status_code == 202 or code == "REQUEST_IN_PROGRESS":
            wait = retry if retry is not None else 1.0
            await self._gate.finish(
                test_id,
                GateState.RECONCILING,
                nonce=nonce,
                retry_delay_seconds=wait,
                http_status=response.status_code,
                retry_after_header=retry_header,
                error_code=code,
            )
            return GateOutcome(GateState.RECONCILING, retry_after_seconds=retry, error_code=code)
        if code == "REPLAYED_REQUEST":
            await self._gate.finish(
                test_id,
                GateState.RECONCILING,
                nonce=nonce,
                http_status=response.status_code,
                retry_after_header=retry_header,
                error_code=code,
            )
            return GateOutcome(GateState.RECONCILING, error_code=code)
        if code == "IDEMPOTENCY_MISMATCH":
            await self._gate.finish(
                test_id,
                GateState.RECONCILING,
                nonce=nonce,
                http_status=response.status_code,
                retry_after_header=retry_header,
                error_code=code,
            )
            return GateOutcome(GateState.RECONCILING, error_code=code)
        if response.status_code == 200:
            try:
                purchase = OrderPurchase(
                    product_id=record.product_id,
                    quantity=record.quantity,
                    max_unit_price=record.max_unit_price_vnd,
                    currency="VND",
                )
                order = parse_order_response(
                    response.body,
                    key=record.idempotency_key,
                    purchase=purchase,
                )
            except (WriteContractError, ValueError, TypeError):
                await self._gate.finish(
                    test_id,
                    GateState.UNKNOWN,
                    nonce=nonce,
                    http_status=response.status_code,
                    retry_after_header=retry_header,
                    error_code="INVALID_RESPONSE",
                )
                return GateOutcome(GateState.UNKNOWN)
            if order.supplier_reported_total > record.absolute_spend_cap_vnd:
                await self._gate.finish(
                    test_id,
                    GateState.RECONCILING,
                    nonce=nonce,
                    http_status=response.status_code,
                    retry_after_header=retry_header,
                    order_code=order.order_code,
                    error_code="SPEND_CAP_EXCEEDED",
                )
                return GateOutcome(GateState.RECONCILING, error_code="SPEND_CAP_EXCEEDED")
            await self._gate.finish(
                test_id,
                GateState.SUCCEEDED,
                nonce=nonce,
                http_status=response.status_code,
                retry_after_header=retry_header,
                order_code=order.order_code,
            )
            return GateOutcome(GateState.SUCCEEDED)
        await self._gate.finish(
            test_id,
            GateState.UNKNOWN,
            nonce=nonce,
            http_status=response.status_code,
            retry_after_header=retry_header,
            error_code=code,
        )
        return GateOutcome(GateState.UNKNOWN, error_code=code)
