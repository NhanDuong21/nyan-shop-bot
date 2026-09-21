"""Injected boundaries for persistence, fake purchase, reconciliation, and delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from nyan_shop_bot.orders.models import (
    DeliveryAttemptRecord,
    OrderAggregate,
    PrepareResult,
    ReconciliationStart,
    SafeFailureCode,
)


class RuntimeSafetySettings(Protocol):
    @property
    def supplier_mode(self) -> str: ...

    @property
    def payment_mode(self) -> str: ...

    @property
    def allow_real_purchases(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class PurchaseCapabilities:
    idempotent_purchase: bool
    reconciliation: bool


@dataclass(frozen=True, slots=True, repr=False)
class SupplierPurchaseRequest:
    request_key: str
    payload: object

    def __repr__(self) -> str:
        return "SupplierPurchaseRequest(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class PurchaseSucceeded:
    supplier_reference: str

    def __repr__(self) -> str:
        return "PurchaseSucceeded(supplier_reference=<redacted>)"


@dataclass(frozen=True, slots=True)
class PurchaseFailedSafe:
    failure_code: SafeFailureCode


@dataclass(frozen=True, slots=True)
class PurchaseAccepted:
    """Non-terminal acceptance that provides no completion evidence."""


type PurchaseResult = PurchaseSucceeded | PurchaseFailedSafe | PurchaseAccepted


@dataclass(frozen=True, slots=True, repr=False)
class ReconciliationSucceeded:
    supplier_reference: str

    def __repr__(self) -> str:
        return "ReconciliationSucceeded(supplier_reference=<redacted>)"


@dataclass(frozen=True, slots=True)
class ReconciliationFailedSafe:
    failure_code: SafeFailureCode


@dataclass(frozen=True, slots=True)
class ReconciliationUnresolved:
    """No authoritative terminal evidence was found."""


type ReconciliationResult = (
    ReconciliationSucceeded | ReconciliationFailedSafe | ReconciliationUnresolved
)


class PurchasePort(Protocol):
    @property
    def supplier_code(self) -> str: ...

    @property
    def capabilities(self) -> PurchaseCapabilities: ...

    async def purchase(self, request: SupplierPurchaseRequest) -> PurchaseResult: ...

    async def reconcile(self, request: SupplierPurchaseRequest) -> ReconciliationResult: ...


@dataclass(frozen=True, slots=True, repr=False)
class DeliveryRequest:
    order_intent_id: str
    attempt_number: int
    delivery_key: str

    def __repr__(self) -> str:
        return f"DeliveryRequest(attempt_number={self.attempt_number}, identities=<redacted>)"


@dataclass(frozen=True, slots=True)
class DeliverySucceeded:
    pass


@dataclass(frozen=True, slots=True)
class DeliveryFailed:
    failure_code: str


type DeliveryResult = DeliverySucceeded | DeliveryFailed


class DeliverySink(Protocol):
    async def deliver(self, request: DeliveryRequest) -> DeliveryResult: ...


class OrderRepository(Protocol):
    async def prepare(self, candidate: OrderAggregate) -> PrepareResult: ...

    async def get(self, intent_id: str) -> OrderAggregate: ...

    async def claim_prepared(self, intent_id: str) -> OrderAggregate | None: ...

    async def record_success(
        self,
        intent_id: str,
        supplier_reference: str,
    ) -> OrderAggregate: ...

    async def record_safe_failure(
        self,
        intent_id: str,
        failure_code: SafeFailureCode,
    ) -> OrderAggregate: ...

    async def record_unknown(self, intent_id: str) -> OrderAggregate: ...

    async def begin_reconciliation(self, intent_id: str) -> ReconciliationStart: ...

    async def create_delivery_attempt(self, intent_id: str) -> DeliveryAttemptRecord: ...

    async def finish_delivery(
        self,
        delivery_id: str,
        *,
        succeeded: bool,
        failure_code: str | None,
    ) -> DeliveryAttemptRecord: ...
