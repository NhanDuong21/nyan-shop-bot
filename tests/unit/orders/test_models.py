"""Money, canonicalization, bounded identity, and state-machine tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from nyan_shop_bot.orders.errors import InvalidOrderInput, OrderStateConflict
from nyan_shop_bot.orders.fakes import InMemoryOrderRepository
from nyan_shop_bot.orders.models import (
    CanonicalPurchasePayload,
    MinorMoney,
    OrderRequest,
    PurchaseState,
    SafeFailureCode,
)
from tests.unit.orders.support import prepared_candidate, request


@pytest.mark.parametrize(
    ("amount", "currency", "unit"),
    (
        (-1, "VND", "minor"),
        (1.5, "VND", "minor"),
        (True, "VND", "minor"),
        (1, "vnd", "minor"),
        (1, "USDX", "minor"),
        (1, "USD", "major"),
    ),
)
def test_money_rejects_float_negative_currency_and_unit_mismatch(
    amount: object,
    currency: str,
    unit: str,
) -> None:
    with pytest.raises(InvalidOrderInput):
        MinorMoney(amount_minor=amount, currency=currency, unit=unit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    (
        {"product_id": ""},
        {"variant_id": " padded"},
        {"idempotency_key": "x" * 129},
        {"idempotency_key": "line\nbreak"},
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": 1.0},
        {"quantity": True},
        {"quantity": 2**31},
    ),
)
def test_request_rejects_empty_unbounded_or_invalid_values(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "product_id": "learning-pass",
        "variant_id": "learning-pass-30d",
        "quantity": 1,
        "idempotency_key": "bounded-key",
        "max_unit_price": MinorMoney(49_000, "VND", "minor"),
    }
    values.update(changes)
    with pytest.raises(InvalidOrderInput):
        OrderRequest(**values)  # type: ignore[arg-type]


def test_canonical_payload_and_sha256_are_stable() -> None:
    payload = prepared_candidate().supplier_attempt.request_payload
    expected = {
        "customer_reference": "synthetic-customer",
        "max_unit_price": {
            "amount_minor": 49_000,
            "currency": "VND",
            "unit": "minor",
        },
        "product_id": "learning-pass",
        "quantity": 1,
        "schema_version": 1,
        "supplier": {
            "code": "fake-supplier",
            "product_id": "supplier-learning-pass",
            "variant_id": "supplier-learning-pass-30d",
        },
        "unit_price": {
            "amount_minor": 49_000,
            "currency": "VND",
            "unit": "minor",
        },
        "variant_id": "learning-pass-30d",
    }
    canonical = json.dumps(expected, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    assert payload.as_dict() == expected
    assert payload.canonical_json() == canonical
    assert payload.fingerprint() == hashlib.sha256(canonical.encode()).hexdigest()
    assert len(payload.fingerprint()) == 64
    assert CanonicalPurchasePayload.from_mapping(expected) == payload


@pytest.mark.parametrize(
    "stored",
    (
        {},
        {"schema_version": 1},
        {"unexpected": "secret-fulfillment-material"},
    ),
)
def test_corrupt_canonical_payload_fails_with_safe_error(stored: object) -> None:
    with pytest.raises(Exception) as caught:
        CanonicalPurchasePayload.from_mapping(stored)
    assert "secret-fulfillment-material" not in str(caught.value)
    assert "secret-fulfillment-material" not in repr(caught.value)


async def test_purchase_state_machine_allows_only_declared_transitions() -> None:
    repository = InMemoryOrderRepository()
    candidate = prepared_candidate()
    prepared = await repository.prepare(candidate)
    assert prepared.aggregate.intent.purchase_state is PurchaseState.PREPARED

    claimed = await repository.claim_prepared(candidate.intent.id)
    assert claimed is not None
    assert claimed.intent.purchase_state is PurchaseState.DISPATCHING
    assert await repository.claim_prepared(candidate.intent.id) is None

    succeeded = await repository.record_success(candidate.intent.id, "fake-reference")
    assert succeeded.intent.purchase_state is PurchaseState.SUCCEEDED
    assert (await repository.record_success(candidate.intent.id, "fake-reference")) == succeeded
    with pytest.raises(OrderStateConflict):
        await repository.record_success(candidate.intent.id, "different-reference")
    with pytest.raises(OrderStateConflict):
        await repository.record_unknown(candidate.intent.id)


async def test_unknown_must_reconcile_before_terminal_resolution() -> None:
    repository = InMemoryOrderRepository()
    candidate = prepared_candidate()
    await repository.prepare(candidate)
    await repository.claim_prepared(candidate.intent.id)
    unknown = await repository.record_unknown(candidate.intent.id)
    assert unknown.intent.purchase_state is PurchaseState.UNKNOWN
    with pytest.raises(OrderStateConflict):
        await repository.record_safe_failure(
            candidate.intent.id,
            SafeFailureCode.OUT_OF_STOCK,
        )

    started = await repository.begin_reconciliation(candidate.intent.id)
    assert started.should_reconcile
    assert started.aggregate.intent.purchase_state is PurchaseState.RECONCILING
    failed = await repository.record_safe_failure(
        candidate.intent.id,
        SafeFailureCode.OUT_OF_STOCK,
    )
    assert failed.intent.purchase_state is PurchaseState.FAILED_SAFE


def test_same_key_binds_to_canonical_payload_not_object_identity() -> None:
    first = prepared_candidate()
    second = replace(
        first,
        supplier_attempt=replace(first.supplier_attempt),
    )
    assert first is not second
    assert first.supplier_attempt.request_payload == second.supplier_attempt.request_payload


def test_request_repr_redacts_every_opaque_identity() -> None:
    value = request(
        key="secret-idempotency-value",
        product_id="secret-product-value",
        variant_id="secret-variant-value",
    )
    rendered = repr(value)
    assert "secret-idempotency-value" not in rendered
    assert "secret-product-value" not in rendered
    assert "secret-variant-value" not in rendered
    assert "identities=<redacted>" in rendered
