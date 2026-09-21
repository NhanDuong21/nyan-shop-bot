"""Strict, redacted domain models for deterministic mock orders."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid5

from nyan_shop_bot.catalog.models import Money
from nyan_shop_bot.orders.errors import InvalidOrderInput, PersistenceInvariantError

MAX_DATABASE_INTEGER = 2**63 - 1
MAX_QUANTITY = 2**31 - 1
ORDER_NAMESPACE = UUID("a426f660-f23b-5d5d-80ef-d9a86380e4fd")


def _validate_identity(value: object, *, maximum: int) -> str:
    if type(value) is not str:
        raise InvalidOrderInput
    if not value or len(value) > maximum or value != value.strip():
        raise InvalidOrderInput
    if not value.isprintable() or unicodedata.normalize("NFC", value) != value:
        raise InvalidOrderInput
    return value


def _validate_integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise InvalidOrderInput
    return value


class PurchaseState(StrEnum):
    PREPARED = "PREPARED"
    DISPATCHING = "DISPATCHING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_SAFE = "FAILED_SAFE"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"


class DeliveryState(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SafeFailureCode(StrEnum):
    PRICE_CHANGED = "PRICE_CHANGED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"


@dataclass(frozen=True, slots=True)
class MinorMoney:
    """Integer minor-unit money with an explicit ISO-style currency code."""

    amount_minor: int
    currency: str
    unit: str

    def __post_init__(self) -> None:
        _validate_integer(self.amount_minor, minimum=0, maximum=MAX_DATABASE_INTEGER)
        if type(self.currency) is not str or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise InvalidOrderInput
        if self.unit != "minor":
            raise InvalidOrderInput

    @classmethod
    def from_catalog(cls, value: Money) -> Self:
        return cls(
            amount_minor=value.amount_minor,
            currency=value.currency,
            unit=value.unit,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True, repr=False)
class OrderRequest:
    """The complete caller-controlled order input; all other values are server-derived."""

    product_id: str
    variant_id: str
    quantity: int
    idempotency_key: str
    max_unit_price: MinorMoney

    def __post_init__(self) -> None:
        _validate_identity(self.product_id, maximum=128)
        _validate_identity(self.variant_id, maximum=128)
        _validate_identity(self.idempotency_key, maximum=128)
        _validate_integer(self.quantity, minimum=1, maximum=MAX_QUANTITY)
        if not isinstance(self.max_unit_price, MinorMoney):
            raise InvalidOrderInput

    def __repr__(self) -> str:
        return (
            "OrderRequest(quantity="
            f"{self.quantity}, max_unit_price={self.max_unit_price!r}, identities=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class CanonicalPurchasePayload:
    """Versioned internal payload persisted before a fake purchase can run."""

    customer_reference: str
    product_id: str
    variant_id: str
    quantity: int
    unit_price: MinorMoney
    max_unit_price: MinorMoney
    supplier_code: str
    supplier_product_id: str
    supplier_variant_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_identity(self.customer_reference, maximum=128)
        _validate_identity(self.product_id, maximum=128)
        _validate_identity(self.variant_id, maximum=128)
        _validate_integer(self.quantity, minimum=1, maximum=MAX_QUANTITY)
        _validate_identity(self.supplier_code, maximum=64)
        _validate_identity(self.supplier_product_id, maximum=128)
        _validate_identity(self.supplier_variant_id, maximum=128)
        if not isinstance(self.unit_price, MinorMoney):
            raise InvalidOrderInput
        if not isinstance(self.max_unit_price, MinorMoney):
            raise InvalidOrderInput
        if self.schema_version != 1:
            raise InvalidOrderInput

    def __repr__(self) -> str:
        return "CanonicalPurchasePayload(<redacted>)"

    def as_dict(self) -> dict[str, object]:
        return {
            "customer_reference": self.customer_reference,
            "max_unit_price": self.max_unit_price.as_dict(),
            "product_id": self.product_id,
            "quantity": self.quantity,
            "schema_version": self.schema_version,
            "supplier": {
                "code": self.supplier_code,
                "product_id": self.supplier_product_id,
                "variant_id": self.supplier_variant_id,
            },
            "unit_price": self.unit_price.as_dict(),
            "variant_id": self.variant_id,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_mapping(cls, raw: object) -> Self:
        """Parse JSONB defensively without echoing corrupt stored values."""
        try:
            if not isinstance(raw, Mapping) or set(raw) != {
                "customer_reference",
                "max_unit_price",
                "product_id",
                "quantity",
                "schema_version",
                "supplier",
                "unit_price",
                "variant_id",
            }:
                raise PersistenceInvariantError
            supplier = raw["supplier"]
            unit_price = raw["unit_price"]
            max_unit_price = raw["max_unit_price"]
            if not isinstance(supplier, Mapping) or set(supplier) != {
                "code",
                "product_id",
                "variant_id",
            }:
                raise PersistenceInvariantError
            return cls(
                customer_reference=raw["customer_reference"],
                product_id=raw["product_id"],
                variant_id=raw["variant_id"],
                quantity=raw["quantity"],
                unit_price=_money_from_mapping(unit_price),
                max_unit_price=_money_from_mapping(max_unit_price),
                supplier_code=supplier["code"],
                supplier_product_id=supplier["product_id"],
                supplier_variant_id=supplier["variant_id"],
                schema_version=raw["schema_version"],
            )
        except (InvalidOrderInput, KeyError, TypeError, ValueError):
            raise PersistenceInvariantError from None


def _money_from_mapping(raw: object) -> MinorMoney:
    if not isinstance(raw, Mapping) or set(raw) != {"amount_minor", "currency", "unit"}:
        raise PersistenceInvariantError
    return MinorMoney(
        amount_minor=raw["amount_minor"],
        currency=raw["currency"],
        unit=raw["unit"],
    )


def intent_id_for(idempotency_key: str) -> str:
    _validate_identity(idempotency_key, maximum=128)
    return str(uuid5(ORDER_NAMESPACE, f"intent:{idempotency_key}"))


def supplier_attempt_id_for(intent_id: str) -> str:
    _validate_identity(intent_id, maximum=36)
    return str(uuid5(ORDER_NAMESPACE, f"supplier-attempt:{intent_id}"))


def supplier_request_key_for(intent_id: str) -> str:
    _validate_identity(intent_id, maximum=36)
    return f"purchase:{intent_id}"


def delivery_attempt_id_for(intent_id: str, attempt_number: int) -> str:
    _validate_identity(intent_id, maximum=36)
    _validate_integer(attempt_number, minimum=1, maximum=MAX_QUANTITY)
    return str(uuid5(ORDER_NAMESPACE, f"delivery:{intent_id}:{attempt_number}"))


def delivery_key_for(intent_id: str, attempt_number: int) -> str:
    _validate_identity(intent_id, maximum=36)
    _validate_integer(attempt_number, minimum=1, maximum=MAX_QUANTITY)
    return f"delivery:{intent_id}:{attempt_number}"


@dataclass(frozen=True, slots=True, repr=False)
class OrderIntentRecord:
    id: str
    idempotency_key: str
    customer_reference: str
    product_id: str
    variant_id: str
    quantity: int
    unit_price: MinorMoney
    max_unit_price: MinorMoney
    purchase_state: PurchaseState

    def __repr__(self) -> str:
        return f"OrderIntentRecord(state={self.purchase_state!r}, identities=<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class SupplierAttemptRecord:
    id: str
    order_intent_id: str
    supplier_code: str
    request_key: str
    request_fingerprint: str
    request_payload: CanonicalPurchasePayload
    status: PurchaseState
    supplier_order_reference: str | None = None
    failure_code: SafeFailureCode | None = None

    def __repr__(self) -> str:
        return f"SupplierAttemptRecord(status={self.status!r}, supplier_data=<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class DeliveryAttemptRecord:
    id: str
    order_intent_id: str
    attempt_number: int
    delivery_key: str
    status: DeliveryState
    failure_code: str | None = None

    def __repr__(self) -> str:
        return (
            f"DeliveryAttemptRecord(attempt_number={self.attempt_number}, "
            f"status={self.status!r}, key=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OrderAggregate:
    intent: OrderIntentRecord
    supplier_attempt: SupplierAttemptRecord
    delivery_attempts: tuple[DeliveryAttemptRecord, ...] = ()

    def __repr__(self) -> str:
        return (
            f"OrderAggregate(state={self.intent.purchase_state!r}, "
            f"delivery_attempts={len(self.delivery_attempts)}, data=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class PrepareResult:
    aggregate: OrderAggregate
    created: bool


@dataclass(frozen=True, slots=True)
class ReconciliationStart:
    aggregate: OrderAggregate
    should_reconcile: bool


@dataclass(frozen=True, slots=True)
class DeliverySnapshot:
    attempt_number: int
    status: DeliveryState
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """Public-safe state with no supplier mapping, reference, or request payload."""

    intent_id: str
    product_id: str
    variant_id: str
    quantity: int
    unit_price: MinorMoney
    max_unit_price: MinorMoney
    purchase_state: PurchaseState
    failure_code: SafeFailureCode | None
    deliveries: tuple[DeliverySnapshot, ...]

    @classmethod
    def from_aggregate(cls, aggregate: OrderAggregate) -> Self:
        return cls(
            intent_id=aggregate.intent.id,
            product_id=aggregate.intent.product_id,
            variant_id=aggregate.intent.variant_id,
            quantity=aggregate.intent.quantity,
            unit_price=aggregate.intent.unit_price,
            max_unit_price=aggregate.intent.max_unit_price,
            purchase_state=aggregate.intent.purchase_state,
            failure_code=aggregate.supplier_attempt.failure_code,
            deliveries=tuple(
                DeliverySnapshot(
                    attempt_number=item.attempt_number,
                    status=item.status,
                    failure_code=item.failure_code,
                )
                for item in aggregate.delivery_attempts
            ),
        )


def build_prepared_order(
    *,
    customer_reference: str,
    request: OrderRequest,
    payload: CanonicalPurchasePayload,
) -> OrderAggregate:
    """Create the only valid pre-dispatch aggregate from canonical data."""
    _validate_identity(customer_reference, maximum=128)
    intent_id = intent_id_for(request.idempotency_key)
    intent = OrderIntentRecord(
        id=intent_id,
        idempotency_key=request.idempotency_key,
        customer_reference=customer_reference,
        product_id=request.product_id,
        variant_id=request.variant_id,
        quantity=request.quantity,
        unit_price=payload.unit_price,
        max_unit_price=request.max_unit_price,
        purchase_state=PurchaseState.PREPARED,
    )
    attempt = SupplierAttemptRecord(
        id=supplier_attempt_id_for(intent_id),
        order_intent_id=intent_id,
        supplier_code=payload.supplier_code,
        request_key=supplier_request_key_for(intent_id),
        request_fingerprint=payload.fingerprint(),
        request_payload=payload,
        status=PurchaseState.PREPARED,
    )
    return OrderAggregate(intent=intent, supplier_attempt=attempt)


def assert_aggregate_invariants(aggregate: OrderAggregate) -> None:
    intent = aggregate.intent
    attempt = aggregate.supplier_attempt
    payload = attempt.request_payload
    valid = (
        intent.id == attempt.order_intent_id
        and intent.purchase_state is attempt.status
        and attempt.request_key == supplier_request_key_for(intent.id)
        and attempt.request_fingerprint == payload.fingerprint()
        and attempt.supplier_code == payload.supplier_code
        and intent.customer_reference == payload.customer_reference
        and intent.product_id == payload.product_id
        and intent.variant_id == payload.variant_id
        and intent.quantity == payload.quantity
        and intent.unit_price == payload.unit_price
        and intent.max_unit_price == payload.max_unit_price
    )
    if not valid:
        raise PersistenceInvariantError


def same_canonical_request(left: OrderAggregate, right: OrderAggregate) -> bool:
    assert_aggregate_invariants(left)
    assert_aggregate_invariants(right)
    return (
        left.supplier_attempt.request_fingerprint == right.supplier_attempt.request_fingerprint
        and left.supplier_attempt.request_payload.canonical_json()
        == right.supplier_attempt.request_payload.canonical_json()
    )
