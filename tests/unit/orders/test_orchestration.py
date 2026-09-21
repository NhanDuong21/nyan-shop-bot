"""Idempotency, uncertainty, reconciliation, and delivery separation tests."""

from __future__ import annotations

import asyncio

import pytest

from nyan_shop_bot.orders.errors import (
    DeliveryNotAllowed,
    IdempotencyConflict,
    SupplierCapabilityRejected,
)
from nyan_shop_bot.orders.fakes import (
    FakeDeliveryOutcome,
    FakeDeliverySink,
    FakePurchaseOutcome,
    FakeReconciliationOutcome,
    FakeSupplierPort,
    InMemoryOrderRepository,
)
from nyan_shop_bot.orders.models import DeliveryState, PurchaseState, SafeFailureCode
from nyan_shop_bot.orders.ports import PurchaseResult, SupplierPurchaseRequest
from tests.unit.orders.support import (
    prepared_candidate,
    request,
    service_bundle,
)


class GatedFakeSupplier(FakeSupplierPort):
    """Pause the sole purchase so a duplicate can observe DISPATCHING."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def purchase(self, request: SupplierPurchaseRequest) -> PurchaseResult:
        self.started.set()
        await self.release.wait()
        return await super().purchase(request)


async def test_same_key_same_payload_returns_existing_without_second_purchase() -> None:
    bundle = service_bundle()
    order_request = request(key="same-request-key")

    first = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=order_request,
    )
    second = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=order_request,
    )

    assert first == second
    assert first.purchase_state is PurchaseState.SUCCEEDED
    assert bundle.supplier.purchase_calls == 1


async def test_same_key_different_payload_is_a_typed_conflict() -> None:
    bundle = service_bundle()
    await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="conflict-key", quantity=1),
    )

    with pytest.raises(IdempotencyConflict):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key="conflict-key", quantity=2),
        )
    assert bundle.supplier.purchase_calls == 1


async def test_concurrent_duplicate_submission_claims_purchase_once() -> None:
    supplier = GatedFakeSupplier()
    bundle = service_bundle(supplier=supplier)
    order_request = request(key="concurrent-key")

    first_task = asyncio.create_task(
        bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=order_request,
        )
    )
    await supplier.started.wait()
    duplicate = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=order_request,
    )
    assert duplicate.purchase_state is PurchaseState.DISPATCHING

    supplier.release.set()
    first = await first_task
    assert first.purchase_state is PurchaseState.SUCCEEDED
    assert supplier.purchase_calls == 1
    stored = await bundle.repository.get(first.intent_id)
    assert stored.supplier_attempt.status is PurchaseState.SUCCEEDED


@pytest.mark.parametrize(
    ("outcome", "failure_code"),
    (
        (FakePurchaseOutcome.PRICE_CHANGED, SafeFailureCode.PRICE_CHANGED),
        (FakePurchaseOutcome.OUT_OF_STOCK, SafeFailureCode.OUT_OF_STOCK),
        (
            FakePurchaseOutcome.INSUFFICIENT_BALANCE,
            SafeFailureCode.INSUFFICIENT_BALANCE,
        ),
    ),
)
async def test_business_failures_are_terminal_and_never_retried(
    outcome: FakePurchaseOutcome,
    failure_code: SafeFailureCode,
) -> None:
    supplier = FakeSupplierPort(purchase_outcome=outcome)
    bundle = service_bundle(supplier=supplier)
    order_request = request(key=f"safe-failure-{outcome.value}")

    first = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=order_request,
    )
    second = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=order_request,
    )
    recovered = await bundle.service.recover(first.intent_id)

    assert first == second == recovered
    assert first.purchase_state is PurchaseState.FAILED_SAFE
    assert first.failure_code is failure_code
    assert supplier.purchase_calls == 1
    assert supplier.reconciliation_calls == 0


@pytest.mark.parametrize(
    "outcome",
    (
        FakePurchaseOutcome.ACCEPTED,
        FakePurchaseOutcome.TIMEOUT,
        FakePurchaseOutcome.EXCEPTION,
    ),
)
async def test_nonterminal_timeout_and_exception_become_unknown(
    outcome: FakePurchaseOutcome,
) -> None:
    supplier = FakeSupplierPort(purchase_outcome=outcome)
    bundle = service_bundle(supplier=supplier)
    snapshot = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key=f"uncertain-{outcome.value}"),
    )

    assert snapshot.purchase_state is PurchaseState.UNKNOWN
    assert snapshot.failure_code is None
    assert supplier.purchase_calls == 1


async def test_cancellation_after_dispatch_is_persisted_unknown_and_reraised() -> None:
    supplier = FakeSupplierPort(purchase_outcome=FakePurchaseOutcome.CANCELLED)
    bundle = service_bundle(supplier=supplier)
    order_request = request(key="cancelled-purchase")

    with pytest.raises(asyncio.CancelledError):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=order_request,
        )
    stored = await bundle.repository.get(prepared_candidate(key="cancelled-purchase").intent.id)
    assert stored.intent.purchase_state is PurchaseState.UNKNOWN
    assert supplier.purchase_calls == 1


async def test_duplicate_terminal_callbacks_record_success_once() -> None:
    repository = InMemoryOrderRepository()
    candidate = prepared_candidate(key="duplicate-callback")
    await repository.prepare(candidate)
    await repository.claim_prepared(candidate.intent.id)

    first, second = await asyncio.gather(
        repository.record_success(candidate.intent.id, "same-fake-reference"),
        repository.record_success(candidate.intent.id, "same-fake-reference"),
    )

    assert first == second
    assert first.intent.purchase_state is PurchaseState.SUCCEEDED
    assert first.supplier_attempt.supplier_order_reference == "same-fake-reference"


async def test_crash_visible_dispatching_reconciles_with_original_request_only() -> None:
    repository = InMemoryOrderRepository()
    candidate = prepared_candidate(key="crash-visible")
    await repository.prepare(candidate)
    claimed = await repository.claim_prepared(candidate.intent.id)
    assert claimed is not None
    supplier = FakeSupplierPort(reconciliation_outcome=FakeReconciliationOutcome.CONFIRMED_SUCCESS)
    bundle = service_bundle(repository=repository, supplier=supplier)

    snapshot = await bundle.service.recover(candidate.intent.id)

    assert snapshot.purchase_state is PurchaseState.SUCCEEDED
    assert supplier.purchase_calls == 0
    assert supplier.reconciliation_calls == 1
    reconciled_request = supplier.reconciliation_requests[0]
    assert reconciled_request.request_key == candidate.supplier_attempt.request_key
    assert reconciled_request.payload == candidate.supplier_attempt.request_payload


@pytest.mark.parametrize(
    ("outcome", "expected_state", "expected_failure"),
    (
        (
            FakeReconciliationOutcome.CONFIRMED_OUT_OF_STOCK,
            PurchaseState.FAILED_SAFE,
            SafeFailureCode.OUT_OF_STOCK,
        ),
        (
            FakeReconciliationOutcome.UNRESOLVED,
            PurchaseState.RECONCILING,
            None,
        ),
        (
            FakeReconciliationOutcome.EXCEPTION,
            PurchaseState.RECONCILING,
            None,
        ),
    ),
)
async def test_reconciliation_records_only_confirmed_evidence(
    outcome: FakeReconciliationOutcome,
    expected_state: PurchaseState,
    expected_failure: SafeFailureCode | None,
) -> None:
    supplier = FakeSupplierPort(
        purchase_outcome=FakePurchaseOutcome.ACCEPTED,
        reconciliation_outcome=outcome,
    )
    bundle = service_bundle(supplier=supplier)
    unknown = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key=f"reconcile-{outcome.value}"),
    )

    recovered = await bundle.service.recover(unknown.intent_id)
    assert recovered.purchase_state is expected_state
    assert recovered.failure_code is expected_failure
    assert supplier.purchase_calls == 1
    assert supplier.reconciliation_calls == 1


async def test_unsupported_reconciliation_stays_safely_unresolved() -> None:
    supplier = FakeSupplierPort(
        purchase_outcome=FakePurchaseOutcome.ACCEPTED,
        reconciliation=False,
    )
    bundle = service_bundle(supplier=supplier)
    unknown = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="unsupported-reconciliation"),
    )

    recovered = await bundle.service.recover(unknown.intent_id)
    assert recovered.purchase_state is PurchaseState.RECONCILING
    assert supplier.purchase_calls == 1
    assert supplier.reconciliation_calls == 0


async def test_non_idempotent_purchase_capability_fails_before_persistence() -> None:
    supplier = FakeSupplierPort(idempotent_purchase=False)
    bundle = service_bundle(supplier=supplier)
    with pytest.raises(SupplierCapabilityRejected):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key="no-idempotency"),
        )
    assert supplier.purchase_calls == 0


async def test_delivery_retries_use_independent_ledger_and_never_repurchase() -> None:
    supplier = FakeSupplierPort()
    delivery = FakeDeliverySink(outcomes=(FakeDeliveryOutcome.FAILURE, FakeDeliveryOutcome.SUCCESS))
    bundle = service_bundle(supplier=supplier, delivery=delivery)
    purchased = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="delivery-retry"),
    )
    stored_before = await bundle.repository.get(purchased.intent_id)

    first = await bundle.service.deliver(purchased.intent_id)
    second = await bundle.service.deliver(purchased.intent_id)
    stored_after = await bundle.repository.get(purchased.intent_id)

    assert [item.status for item in first.deliveries] == [DeliveryState.FAILED]
    assert [item.status for item in second.deliveries] == [
        DeliveryState.FAILED,
        DeliveryState.SUCCEEDED,
    ]
    assert [item.attempt_number for item in second.deliveries] == [1, 2]
    assert supplier.purchase_calls == 1
    assert delivery.calls == 2
    assert stored_after.supplier_attempt.id == stored_before.supplier_attempt.id
    assert stored_after.supplier_attempt.request_key == stored_before.supplier_attempt.request_key


async def test_delivery_cannot_start_before_purchase_success() -> None:
    supplier = FakeSupplierPort(purchase_outcome=FakePurchaseOutcome.ACCEPTED)
    bundle = service_bundle(supplier=supplier)
    unknown = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="delivery-before-success"),
    )
    with pytest.raises(DeliveryNotAllowed):
        await bundle.service.deliver(unknown.intent_id)
    assert bundle.delivery.calls == 0
    assert supplier.purchase_calls == 1


def test_order_ports_offer_no_failover_refund_or_topup_operation() -> None:
    supplier = FakeSupplierPort()
    for forbidden in ("failover", "refund", "top_up", "payment", "deliver"):
        assert not hasattr(supplier, forbidden)
