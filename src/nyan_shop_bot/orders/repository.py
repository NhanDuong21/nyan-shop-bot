"""PostgreSQL persistence for the coordinator-owned order tables."""

from __future__ import annotations

from dataclasses import replace

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nyan_shop_bot.orders.errors import (
    DeliveryNotAllowed,
    IdempotencyConflict,
    InvalidOrderInput,
    OrderNotFound,
    OrderStateConflict,
    PersistenceInvariantError,
)
from nyan_shop_bot.orders.models import (
    CanonicalPurchasePayload,
    DeliveryAttemptRecord,
    DeliveryState,
    MinorMoney,
    OrderAggregate,
    OrderIntentRecord,
    PrepareResult,
    PurchaseState,
    ReconciliationStart,
    SafeFailureCode,
    SupplierAttemptRecord,
    assert_aggregate_invariants,
    delivery_attempt_id_for,
    delivery_key_for,
    same_canonical_request,
)

_metadata = sa.MetaData()

_order_intents = sa.Table(
    "order_intents",
    _metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("idempotency_key", sa.String(128), nullable=False),
    sa.Column("customer_reference", sa.String(128), nullable=False),
    sa.Column("product_id", sa.String(128), nullable=False),
    sa.Column("variant_id", sa.String(128), nullable=False),
    sa.Column("quantity", sa.Integer, nullable=False),
    sa.Column("unit_price_minor", sa.BigInteger, nullable=False),
    sa.Column("max_unit_price_minor", sa.BigInteger, nullable=False),
    sa.Column("currency", sa.String(8), nullable=False),
    sa.Column("money_unit", sa.String(32), nullable=False),
    sa.Column("purchase_state", sa.String(32), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)

_supplier_attempts = sa.Table(
    "supplier_order_attempts",
    _metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("order_intent_id", sa.String(36), nullable=False),
    sa.Column("supplier_code", sa.String(64), nullable=False),
    sa.Column("request_key", sa.String(128), nullable=False),
    sa.Column("request_fingerprint", sa.String(64), nullable=False),
    sa.Column("request_payload", JSONB, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("supplier_order_reference", sa.String(128), nullable=True),
    sa.Column("failure_code", sa.String(64), nullable=True),
    sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)

_delivery_attempts = sa.Table(
    "delivery_attempts",
    _metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("order_intent_id", sa.String(36), nullable=False),
    sa.Column("attempt_number", sa.Integer, nullable=False),
    sa.Column("delivery_key", sa.String(128), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("failure_code", sa.String(64), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


class PostgresOrderRepository:
    """Async repository whose transactions and row locks cross process boundaries."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def prepare(self, candidate: OrderAggregate) -> PrepareResult:
        """Atomically insert one intent and its sole PREPARED supplier attempt."""
        assert_aggregate_invariants(candidate)
        intent = candidate.intent
        attempt = candidate.supplier_attempt
        async with self._sessions() as session:
            async with session.begin():
                statement = (
                    postgres_insert(_order_intents)
                    .values(
                        id=intent.id,
                        idempotency_key=intent.idempotency_key,
                        customer_reference=intent.customer_reference,
                        product_id=intent.product_id,
                        variant_id=intent.variant_id,
                        quantity=intent.quantity,
                        unit_price_minor=intent.unit_price.amount_minor,
                        max_unit_price_minor=intent.max_unit_price.amount_minor,
                        currency=intent.unit_price.currency,
                        money_unit=intent.unit_price.unit,
                        purchase_state=PurchaseState.PREPARED.value,
                    )
                    .on_conflict_do_nothing(index_elements=[_order_intents.c.idempotency_key])
                    .returning(_order_intents.c.id)
                )
                created_id = (await session.execute(statement)).scalar_one_or_none()
                if created_id is not None:
                    await session.execute(
                        sa.insert(_supplier_attempts).values(
                            id=attempt.id,
                            order_intent_id=attempt.order_intent_id,
                            supplier_code=attempt.supplier_code,
                            request_key=attempt.request_key,
                            request_fingerprint=attempt.request_fingerprint,
                            request_payload=attempt.request_payload.as_dict(),
                            status=PurchaseState.PREPARED.value,
                        )
                    )
                    result = PrepareResult(aggregate=candidate, created=True)
                else:
                    existing = await self._load_by_key(
                        session,
                        intent.idempotency_key,
                        for_update=True,
                    )
                    if not same_canonical_request(existing, candidate):
                        raise IdempotencyConflict
                    result = PrepareResult(aggregate=existing, created=False)
        return result

    async def get(self, intent_id: str) -> OrderAggregate:
        async with self._sessions() as session:
            return await self._load(session, intent_id, for_update=False)

    async def claim_prepared(self, intent_id: str) -> OrderAggregate | None:
        """Commit DISPATCHING before returning authority to invoke the fake port."""
        async with self._sessions() as session:
            async with session.begin():
                aggregate = await self._load(session, intent_id, for_update=True)
                if aggregate.intent.purchase_state is not PurchaseState.PREPARED:
                    return None
                await session.execute(
                    sa.update(_order_intents)
                    .where(_order_intents.c.id == intent_id)
                    .values(
                        purchase_state=PurchaseState.DISPATCHING.value,
                        updated_at=sa.func.now(),
                    )
                )
                await session.execute(
                    sa.update(_supplier_attempts)
                    .where(_supplier_attempts.c.order_intent_id == intent_id)
                    .values(
                        status=PurchaseState.DISPATCHING.value,
                        dispatched_at=sa.func.now(),
                        updated_at=sa.func.now(),
                    )
                )
                claimed = _replace_purchase(
                    aggregate,
                    state=PurchaseState.DISPATCHING,
                )
        return claimed

    async def record_success(
        self,
        intent_id: str,
        supplier_reference: str,
    ) -> OrderAggregate:
        _validate_safe_text(supplier_reference, maximum=128)
        return await self._record_terminal(
            intent_id,
            state=PurchaseState.SUCCEEDED,
            supplier_reference=supplier_reference,
            failure_code=None,
        )

    async def record_safe_failure(
        self,
        intent_id: str,
        failure_code: SafeFailureCode,
    ) -> OrderAggregate:
        if not isinstance(failure_code, SafeFailureCode):
            raise InvalidOrderInput
        return await self._record_terminal(
            intent_id,
            state=PurchaseState.FAILED_SAFE,
            supplier_reference=None,
            failure_code=failure_code,
        )

    async def record_unknown(self, intent_id: str) -> OrderAggregate:
        async with self._sessions() as session:
            async with session.begin():
                aggregate = await self._load(session, intent_id, for_update=True)
                current = aggregate.intent.purchase_state
                if current in (PurchaseState.UNKNOWN, PurchaseState.RECONCILING):
                    return aggregate
                if current is not PurchaseState.DISPATCHING:
                    raise OrderStateConflict
                await self._set_purchase_state(
                    session,
                    intent_id,
                    state=PurchaseState.UNKNOWN,
                    supplier_reference=None,
                    failure_code=None,
                    resolved=False,
                )
                updated = _replace_purchase(aggregate, state=PurchaseState.UNKNOWN)
        return updated

    async def begin_reconciliation(self, intent_id: str) -> ReconciliationStart:
        async with self._sessions() as session:
            async with session.begin():
                aggregate = await self._load(session, intent_id, for_update=True)
                current = aggregate.intent.purchase_state
                if current is PurchaseState.UNKNOWN:
                    await self._set_purchase_state(
                        session,
                        intent_id,
                        state=PurchaseState.RECONCILING,
                        supplier_reference=None,
                        failure_code=None,
                        resolved=False,
                    )
                    aggregate = _replace_purchase(
                        aggregate,
                        state=PurchaseState.RECONCILING,
                    )
                    result = ReconciliationStart(
                        aggregate=aggregate,
                        should_reconcile=True,
                    )
                elif current is PurchaseState.RECONCILING:
                    result = ReconciliationStart(
                        aggregate=aggregate,
                        should_reconcile=True,
                    )
                elif current in (PurchaseState.SUCCEEDED, PurchaseState.FAILED_SAFE):
                    result = ReconciliationStart(
                        aggregate=aggregate,
                        should_reconcile=False,
                    )
                else:
                    raise OrderStateConflict
        return result

    async def create_delivery_attempt(self, intent_id: str) -> DeliveryAttemptRecord:
        """Serialize numbering with an order-row lock, independently of purchase attempts."""
        async with self._sessions() as session:
            async with session.begin():
                aggregate = await self._load(session, intent_id, for_update=True)
                if aggregate.intent.purchase_state is not PurchaseState.SUCCEEDED:
                    raise DeliveryNotAllowed
                number = (
                    max(
                        (item.attempt_number for item in aggregate.delivery_attempts),
                        default=0,
                    )
                    + 1
                )
                attempt = DeliveryAttemptRecord(
                    id=delivery_attempt_id_for(intent_id, number),
                    order_intent_id=intent_id,
                    attempt_number=number,
                    delivery_key=delivery_key_for(intent_id, number),
                    status=DeliveryState.PENDING,
                )
                await session.execute(
                    sa.insert(_delivery_attempts).values(
                        id=attempt.id,
                        order_intent_id=attempt.order_intent_id,
                        attempt_number=attempt.attempt_number,
                        delivery_key=attempt.delivery_key,
                        status=attempt.status.value,
                    )
                )
        return attempt

    async def finish_delivery(
        self,
        delivery_id: str,
        *,
        succeeded: bool,
        failure_code: str | None,
    ) -> DeliveryAttemptRecord:
        target = DeliveryState.SUCCEEDED if succeeded else DeliveryState.FAILED
        expected_failure = None if succeeded else failure_code
        if not succeeded:
            _validate_safe_text(failure_code, maximum=64)
        async with self._sessions() as session:
            async with session.begin():
                statement = (
                    sa.select(_delivery_attempts)
                    .where(_delivery_attempts.c.id == delivery_id)
                    .with_for_update()
                )
                row = (await session.execute(statement)).mappings().one_or_none()
                if row is None:
                    raise OrderNotFound
                attempt = _delivery_from_row(row)
                if attempt.status is not DeliveryState.PENDING:
                    if attempt.status is target and attempt.failure_code == expected_failure:
                        return attempt
                    raise OrderStateConflict
                await session.execute(
                    sa.update(_delivery_attempts)
                    .where(_delivery_attempts.c.id == delivery_id)
                    .values(
                        status=target.value,
                        failure_code=expected_failure,
                        completed_at=sa.func.now(),
                        updated_at=sa.func.now(),
                    )
                )
                updated = replace(
                    attempt,
                    status=target,
                    failure_code=expected_failure,
                )
        return updated

    async def _record_terminal(
        self,
        intent_id: str,
        *,
        state: PurchaseState,
        supplier_reference: str | None,
        failure_code: SafeFailureCode | None,
    ) -> OrderAggregate:
        async with self._sessions() as session:
            async with session.begin():
                aggregate = await self._load(session, intent_id, for_update=True)
                current = aggregate.intent.purchase_state
                if current is state:
                    same_metadata = (
                        aggregate.supplier_attempt.supplier_order_reference == supplier_reference
                        and aggregate.supplier_attempt.failure_code is failure_code
                    )
                    if not same_metadata:
                        raise OrderStateConflict
                    return aggregate
                if current not in (PurchaseState.DISPATCHING, PurchaseState.RECONCILING):
                    raise OrderStateConflict
                await self._set_purchase_state(
                    session,
                    intent_id,
                    state=state,
                    supplier_reference=supplier_reference,
                    failure_code=failure_code,
                    resolved=True,
                )
                updated = _replace_purchase(
                    aggregate,
                    state=state,
                    supplier_reference=supplier_reference,
                    failure_code=failure_code,
                )
        return updated

    async def _set_purchase_state(
        self,
        session: AsyncSession,
        intent_id: str,
        *,
        state: PurchaseState,
        supplier_reference: str | None,
        failure_code: SafeFailureCode | None,
        resolved: bool,
    ) -> None:
        await session.execute(
            sa.update(_order_intents)
            .where(_order_intents.c.id == intent_id)
            .values(purchase_state=state.value, updated_at=sa.func.now())
        )
        attempt_values: dict[str, object] = {
            "status": state.value,
            "supplier_order_reference": supplier_reference,
            "failure_code": failure_code.value if failure_code is not None else None,
            "updated_at": sa.func.now(),
        }
        if resolved:
            attempt_values["resolved_at"] = sa.func.now()
        await session.execute(
            sa.update(_supplier_attempts)
            .where(_supplier_attempts.c.order_intent_id == intent_id)
            .values(**attempt_values)
        )

    async def _load_by_key(
        self,
        session: AsyncSession,
        idempotency_key: str,
        *,
        for_update: bool,
    ) -> OrderAggregate:
        statement = sa.select(_order_intents.c.id).where(
            _order_intents.c.idempotency_key == idempotency_key
        )
        if for_update:
            statement = statement.with_for_update()
        intent_id = (await session.execute(statement)).scalar_one_or_none()
        if intent_id is None:
            raise PersistenceInvariantError
        return await self._load(session, str(intent_id), for_update=False)

    async def _load(
        self,
        session: AsyncSession,
        intent_id: str,
        *,
        for_update: bool,
    ) -> OrderAggregate:
        intent_statement = sa.select(_order_intents).where(_order_intents.c.id == intent_id)
        if for_update:
            intent_statement = intent_statement.with_for_update()
        intent_row = (await session.execute(intent_statement)).mappings().one_or_none()
        if intent_row is None:
            raise OrderNotFound
        attempt_row = (
            (
                await session.execute(
                    sa.select(_supplier_attempts).where(
                        _supplier_attempts.c.order_intent_id == intent_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if attempt_row is None:
            raise PersistenceInvariantError
        delivery_rows = (
            (
                await session.execute(
                    sa.select(_delivery_attempts)
                    .where(_delivery_attempts.c.order_intent_id == intent_id)
                    .order_by(_delivery_attempts.c.attempt_number)
                )
            )
            .mappings()
            .all()
        )
        aggregate = OrderAggregate(
            intent=_intent_from_row(intent_row),
            supplier_attempt=_attempt_from_row(attempt_row),
            delivery_attempts=tuple(_delivery_from_row(row) for row in delivery_rows),
        )
        assert_aggregate_invariants(aggregate)
        return aggregate


def _intent_from_row(row: RowMapping) -> OrderIntentRecord:
    unit_price = MinorMoney(
        amount_minor=_required_int(row, "unit_price_minor"),
        currency=_required_str(row, "currency"),
        unit=_required_str(row, "money_unit"),
    )
    max_unit_price = MinorMoney(
        amount_minor=_required_int(row, "max_unit_price_minor"),
        currency=unit_price.currency,
        unit=unit_price.unit,
    )
    try:
        state = PurchaseState(_required_str(row, "purchase_state"))
    except ValueError:
        raise PersistenceInvariantError from None
    return OrderIntentRecord(
        id=_required_str(row, "id"),
        idempotency_key=_required_str(row, "idempotency_key"),
        customer_reference=_required_str(row, "customer_reference"),
        product_id=_required_str(row, "product_id"),
        variant_id=_required_str(row, "variant_id"),
        quantity=_required_int(row, "quantity"),
        unit_price=unit_price,
        max_unit_price=max_unit_price,
        purchase_state=state,
    )


def _attempt_from_row(row: RowMapping) -> SupplierAttemptRecord:
    try:
        state = PurchaseState(_required_str(row, "status"))
        failure_text = _optional_str(row, "failure_code")
        failure_code = SafeFailureCode(failure_text) if failure_text is not None else None
    except ValueError:
        raise PersistenceInvariantError from None
    return SupplierAttemptRecord(
        id=_required_str(row, "id"),
        order_intent_id=_required_str(row, "order_intent_id"),
        supplier_code=_required_str(row, "supplier_code"),
        request_key=_required_str(row, "request_key"),
        request_fingerprint=_required_str(row, "request_fingerprint"),
        request_payload=CanonicalPurchasePayload.from_mapping(row.get("request_payload")),
        status=state,
        supplier_order_reference=_optional_str(row, "supplier_order_reference"),
        failure_code=failure_code,
    )


def _delivery_from_row(row: RowMapping) -> DeliveryAttemptRecord:
    try:
        state = DeliveryState(_required_str(row, "status"))
    except ValueError:
        raise PersistenceInvariantError from None
    return DeliveryAttemptRecord(
        id=_required_str(row, "id"),
        order_intent_id=_required_str(row, "order_intent_id"),
        attempt_number=_required_int(row, "attempt_number"),
        delivery_key=_required_str(row, "delivery_key"),
        status=state,
        failure_code=_optional_str(row, "failure_code"),
    )


def _required_str(row: RowMapping, key: str) -> str:
    value = row.get(key)
    if type(value) is not str:
        raise PersistenceInvariantError
    return value


def _optional_str(row: RowMapping, key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise PersistenceInvariantError
    return value


def _required_int(row: RowMapping, key: str) -> int:
    value = row.get(key)
    if type(value) is not int:
        raise PersistenceInvariantError
    return value


def _replace_purchase(
    aggregate: OrderAggregate,
    *,
    state: PurchaseState,
    supplier_reference: str | None = None,
    failure_code: SafeFailureCode | None = None,
) -> OrderAggregate:
    return replace(
        aggregate,
        intent=replace(aggregate.intent, purchase_state=state),
        supplier_attempt=replace(
            aggregate.supplier_attempt,
            status=state,
            supplier_order_reference=supplier_reference,
            failure_code=failure_code,
        ),
    )


def _validate_safe_text(value: object, *, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise InvalidOrderInput
    if value != value.strip() or not value.isprintable():
        raise InvalidOrderInput
    return value
