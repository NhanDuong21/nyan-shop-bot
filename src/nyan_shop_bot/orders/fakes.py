"""Deterministic in-memory fakes; none of these objects perform I/O."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import StrEnum

from nyan_shop_bot.orders.errors import (
    AmbiguousPurchaseError,
    DeliveryNotAllowed,
    IdempotencyConflict,
    InvalidOrderInput,
    OrderNotFound,
    OrderStateConflict,
)
from nyan_shop_bot.orders.models import (
    CanonicalPurchasePayload,
    DeliveryAttemptRecord,
    DeliveryState,
    OrderAggregate,
    PrepareResult,
    PurchaseState,
    ReconciliationStart,
    SafeFailureCode,
    assert_aggregate_invariants,
    delivery_attempt_id_for,
    delivery_key_for,
    same_canonical_request,
)
from nyan_shop_bot.orders.ports import (
    DeliveryFailed,
    DeliveryRequest,
    DeliveryResult,
    DeliverySucceeded,
    PurchaseAccepted,
    PurchaseCapabilities,
    PurchaseFailedSafe,
    PurchaseResult,
    PurchaseSucceeded,
    ReconciliationFailedSafe,
    ReconciliationResult,
    ReconciliationSucceeded,
    ReconciliationUnresolved,
    SupplierPurchaseRequest,
)


@dataclass(slots=True)
class FakeRuntimeSettings:
    """Mutable modes let tests prove that every execution rechecks safety."""

    supplier_mode: str = "mock"
    payment_mode: str = "disabled"
    allow_real_purchases: bool = False


class FakePurchaseOutcome(StrEnum):
    SUCCESS = "success"
    PRICE_CHANGED = "price_changed"
    OUT_OF_STOCK = "out_of_stock"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    ACCEPTED = "accepted"
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"


class FakeReconciliationOutcome(StrEnum):
    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_PRICE_CHANGED = "confirmed_price_changed"
    CONFIRMED_OUT_OF_STOCK = "confirmed_out_of_stock"
    CONFIRMED_INSUFFICIENT_BALANCE = "confirmed_insufficient_balance"
    UNRESOLVED = "unresolved"
    EXCEPTION = "exception"


class FakeSupplierPort:
    """One synthetic supplier with explicit idempotency and reconciliation truth."""

    def __init__(
        self,
        *,
        purchase_outcome: FakePurchaseOutcome = FakePurchaseOutcome.SUCCESS,
        reconciliation_outcome: FakeReconciliationOutcome = (FakeReconciliationOutcome.UNRESOLVED),
        idempotent_purchase: bool = True,
        reconciliation: bool = True,
        supplier_code: str = "fake-supplier",
    ) -> None:
        if not supplier_code or len(supplier_code) > 64 or not supplier_code.isprintable():
            raise InvalidOrderInput
        self._supplier_code = supplier_code
        self._capabilities = PurchaseCapabilities(
            idempotent_purchase=idempotent_purchase,
            reconciliation=reconciliation,
        )
        self.purchase_outcome = purchase_outcome
        self.reconciliation_outcome = reconciliation_outcome
        self._purchase_requests: list[SupplierPurchaseRequest] = []
        self._reconciliation_requests: list[SupplierPurchaseRequest] = []

    def __repr__(self) -> str:
        return (
            "FakeSupplierPort("
            f"purchase_calls={self.purchase_calls}, "
            f"reconciliation_calls={self.reconciliation_calls}, data=<redacted>)"
        )

    @property
    def supplier_code(self) -> str:
        return self._supplier_code

    @property
    def capabilities(self) -> PurchaseCapabilities:
        return self._capabilities

    @property
    def purchase_calls(self) -> int:
        return len(self._purchase_requests)

    @property
    def reconciliation_calls(self) -> int:
        return len(self._reconciliation_requests)

    @property
    def purchase_requests(self) -> tuple[SupplierPurchaseRequest, ...]:
        return tuple(self._purchase_requests)

    @property
    def reconciliation_requests(self) -> tuple[SupplierPurchaseRequest, ...]:
        return tuple(self._reconciliation_requests)

    async def purchase(self, request: SupplierPurchaseRequest) -> PurchaseResult:
        self._validate_request(request)
        self._purchase_requests.append(request)
        match self.purchase_outcome:
            case FakePurchaseOutcome.SUCCESS:
                return PurchaseSucceeded(supplier_reference="fake-success-reference")
            case FakePurchaseOutcome.PRICE_CHANGED:
                return PurchaseFailedSafe(SafeFailureCode.PRICE_CHANGED)
            case FakePurchaseOutcome.OUT_OF_STOCK:
                return PurchaseFailedSafe(SafeFailureCode.OUT_OF_STOCK)
            case FakePurchaseOutcome.INSUFFICIENT_BALANCE:
                return PurchaseFailedSafe(SafeFailureCode.INSUFFICIENT_BALANCE)
            case FakePurchaseOutcome.ACCEPTED:
                return PurchaseAccepted()
            case FakePurchaseOutcome.TIMEOUT:
                raise TimeoutError("Deterministic fake timeout without terminal evidence.")
            case FakePurchaseOutcome.EXCEPTION:
                raise AmbiguousPurchaseError
            case FakePurchaseOutcome.CANCELLED:
                raise asyncio.CancelledError

    async def reconcile(self, request: SupplierPurchaseRequest) -> ReconciliationResult:
        if not self.capabilities.reconciliation:
            raise AssertionError("Unsupported reconciliation must never be invoked.")
        self._validate_request(request)
        self._reconciliation_requests.append(request)
        match self.reconciliation_outcome:
            case FakeReconciliationOutcome.CONFIRMED_SUCCESS:
                return ReconciliationSucceeded(supplier_reference="fake-reconciled-reference")
            case FakeReconciliationOutcome.CONFIRMED_PRICE_CHANGED:
                return ReconciliationFailedSafe(SafeFailureCode.PRICE_CHANGED)
            case FakeReconciliationOutcome.CONFIRMED_OUT_OF_STOCK:
                return ReconciliationFailedSafe(SafeFailureCode.OUT_OF_STOCK)
            case FakeReconciliationOutcome.CONFIRMED_INSUFFICIENT_BALANCE:
                return ReconciliationFailedSafe(SafeFailureCode.INSUFFICIENT_BALANCE)
            case FakeReconciliationOutcome.UNRESOLVED:
                return ReconciliationUnresolved()
            case FakeReconciliationOutcome.EXCEPTION:
                raise AmbiguousPurchaseError

    def _validate_request(self, request: SupplierPurchaseRequest) -> None:
        if not isinstance(request.payload, CanonicalPurchasePayload):
            raise InvalidOrderInput
        if request.payload.supplier_code != self.supplier_code:
            raise InvalidOrderInput
        if not request.request_key or len(request.request_key) > 128:
            raise InvalidOrderInput


class FakeDeliveryOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    EXCEPTION = "exception"


class FakeDeliverySink:
    """Synthetic notification sink that never contains fulfillment material."""

    def __init__(
        self,
        outcomes: tuple[FakeDeliveryOutcome, ...] = (FakeDeliveryOutcome.SUCCESS,),
    ) -> None:
        if not outcomes:
            raise InvalidOrderInput
        self._outcomes = outcomes
        self._requests: list[DeliveryRequest] = []

    def __repr__(self) -> str:
        return f"FakeDeliverySink(calls={self.calls}, data=<redacted>)"

    @property
    def calls(self) -> int:
        return len(self._requests)

    @property
    def requests(self) -> tuple[DeliveryRequest, ...]:
        return tuple(self._requests)

    async def deliver(self, request: DeliveryRequest) -> DeliveryResult:
        self._requests.append(request)
        index = min(len(self._requests) - 1, len(self._outcomes) - 1)
        match self._outcomes[index]:
            case FakeDeliveryOutcome.SUCCESS:
                return DeliverySucceeded()
            case FakeDeliveryOutcome.FAILURE:
                return DeliveryFailed(failure_code="FAKE_DELIVERY_FAILURE")
            case FakeDeliveryOutcome.EXCEPTION:
                raise RuntimeError("Deterministic fake delivery failure.")


class InMemoryOrderRepository:
    """Test-only fake; PostgreSQL remains authoritative for real concurrency."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_id: dict[str, OrderAggregate] = {}
        self._id_by_key: dict[str, str] = {}

    async def prepare(self, candidate: OrderAggregate) -> PrepareResult:
        assert_aggregate_invariants(candidate)
        async with self._lock:
            existing_id = self._id_by_key.get(candidate.intent.idempotency_key)
            if existing_id is not None:
                existing = self._by_id[existing_id]
                if not same_canonical_request(existing, candidate):
                    raise IdempotencyConflict
                return PrepareResult(aggregate=existing, created=False)
            self._by_id[candidate.intent.id] = candidate
            self._id_by_key[candidate.intent.idempotency_key] = candidate.intent.id
            return PrepareResult(aggregate=candidate, created=True)

    async def get(self, intent_id: str) -> OrderAggregate:
        async with self._lock:
            try:
                return self._by_id[intent_id]
            except KeyError:
                raise OrderNotFound from None

    async def claim_prepared(self, intent_id: str) -> OrderAggregate | None:
        async with self._lock:
            aggregate = self._require(intent_id)
            if aggregate.intent.purchase_state is not PurchaseState.PREPARED:
                return None
            updated = _replace_purchase(aggregate, state=PurchaseState.DISPATCHING)
            self._by_id[intent_id] = updated
            return updated

    async def record_success(
        self,
        intent_id: str,
        supplier_reference: str,
    ) -> OrderAggregate:
        _validate_safe_text(supplier_reference, maximum=128)
        async with self._lock:
            aggregate = self._require(intent_id)
            current = aggregate.intent.purchase_state
            if current is PurchaseState.SUCCEEDED:
                if aggregate.supplier_attempt.supplier_order_reference != supplier_reference:
                    raise OrderStateConflict
                return aggregate
            if current not in (PurchaseState.DISPATCHING, PurchaseState.RECONCILING):
                raise OrderStateConflict
            updated = _replace_purchase(
                aggregate,
                state=PurchaseState.SUCCEEDED,
                supplier_reference=supplier_reference,
            )
            self._by_id[intent_id] = updated
            return updated

    async def record_safe_failure(
        self,
        intent_id: str,
        failure_code: SafeFailureCode,
    ) -> OrderAggregate:
        async with self._lock:
            aggregate = self._require(intent_id)
            current = aggregate.intent.purchase_state
            if current is PurchaseState.FAILED_SAFE:
                if aggregate.supplier_attempt.failure_code is not failure_code:
                    raise OrderStateConflict
                return aggregate
            if current not in (PurchaseState.DISPATCHING, PurchaseState.RECONCILING):
                raise OrderStateConflict
            updated = _replace_purchase(
                aggregate,
                state=PurchaseState.FAILED_SAFE,
                failure_code=failure_code,
            )
            self._by_id[intent_id] = updated
            return updated

    async def record_unknown(self, intent_id: str) -> OrderAggregate:
        async with self._lock:
            aggregate = self._require(intent_id)
            current = aggregate.intent.purchase_state
            if current in (PurchaseState.UNKNOWN, PurchaseState.RECONCILING):
                return aggregate
            if current is not PurchaseState.DISPATCHING:
                raise OrderStateConflict
            updated = _replace_purchase(aggregate, state=PurchaseState.UNKNOWN)
            self._by_id[intent_id] = updated
            return updated

    async def begin_reconciliation(self, intent_id: str) -> ReconciliationStart:
        async with self._lock:
            aggregate = self._require(intent_id)
            current = aggregate.intent.purchase_state
            if current is PurchaseState.UNKNOWN:
                aggregate = _replace_purchase(
                    aggregate,
                    state=PurchaseState.RECONCILING,
                )
                self._by_id[intent_id] = aggregate
                return ReconciliationStart(aggregate=aggregate, should_reconcile=True)
            if current is PurchaseState.RECONCILING:
                return ReconciliationStart(aggregate=aggregate, should_reconcile=True)
            if current in (PurchaseState.SUCCEEDED, PurchaseState.FAILED_SAFE):
                return ReconciliationStart(aggregate=aggregate, should_reconcile=False)
            raise OrderStateConflict

    async def create_delivery_attempt(self, intent_id: str) -> DeliveryAttemptRecord:
        async with self._lock:
            aggregate = self._require(intent_id)
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
            updated = replace(
                aggregate,
                delivery_attempts=(*aggregate.delivery_attempts, attempt),
            )
            self._by_id[intent_id] = updated
            return attempt

    async def finish_delivery(
        self,
        delivery_id: str,
        *,
        succeeded: bool,
        failure_code: str | None,
    ) -> DeliveryAttemptRecord:
        async with self._lock:
            intent_id, index, attempt = self._find_delivery(delivery_id)
            target = DeliveryState.SUCCEEDED if succeeded else DeliveryState.FAILED
            expected_failure = None if succeeded else failure_code
            if not succeeded:
                _validate_safe_text(failure_code, maximum=64)
            if attempt.status is not DeliveryState.PENDING:
                if attempt.status is target and attempt.failure_code == expected_failure:
                    return attempt
                raise OrderStateConflict
            updated_attempt = replace(
                attempt,
                status=target,
                failure_code=expected_failure,
            )
            aggregate = self._by_id[intent_id]
            deliveries = list(aggregate.delivery_attempts)
            deliveries[index] = updated_attempt
            self._by_id[intent_id] = replace(
                aggregate,
                delivery_attempts=tuple(deliveries),
            )
            return updated_attempt

    def _require(self, intent_id: str) -> OrderAggregate:
        try:
            return self._by_id[intent_id]
        except KeyError:
            raise OrderNotFound from None

    def _find_delivery(
        self,
        delivery_id: str,
    ) -> tuple[str, int, DeliveryAttemptRecord]:
        for intent_id, aggregate in self._by_id.items():
            for index, attempt in enumerate(aggregate.delivery_attempts):
                if attempt.id == delivery_id:
                    return intent_id, index, attempt
        raise OrderNotFound


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
