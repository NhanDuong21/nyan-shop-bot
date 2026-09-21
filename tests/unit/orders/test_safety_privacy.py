"""Execution mode, network, capability, and redaction safety evidence."""

from __future__ import annotations

import socket
from dataclasses import asdict

import pytest

from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.catalog.models import CapabilityStatus, CatalogDetailResponse
from nyan_shop_bot.orders.errors import OrderNotFound, UnsafeOrderExecution
from nyan_shop_bot.orders.fakes import FakeRuntimeSettings
from nyan_shop_bot.orders.models import (
    CanonicalPurchasePayload,
    MinorMoney,
    OrderRequest,
    build_prepared_order,
    intent_id_for,
)
from nyan_shop_bot.orders.ports import SupplierPurchaseRequest
from nyan_shop_bot.orders.service import assert_safe_execution
from tests.unit.orders.support import (
    StubCatalogReader,
    fresh_response,
    primary_product,
    request,
    service_bundle,
)


class RuntimeMutatingCatalog(StubCatalogReader):
    def __init__(self, runtime: FakeRuntimeSettings) -> None:
        super().__init__(response=fresh_response())
        self._runtime = runtime

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        detail = await super().get_product(product_id)
        self._runtime.supplier_mode = "live"
        return detail


@pytest.mark.parametrize(
    "runtime",
    (
        FakeRuntimeSettings(supplier_mode="live"),
        FakeRuntimeSettings(payment_mode="mock"),
        FakeRuntimeSettings(payment_mode="live"),
        FakeRuntimeSettings(allow_real_purchases=True),
        FakeRuntimeSettings(supplier_mode="MOCK"),
        FakeRuntimeSettings(allow_real_purchases=1),  # type: ignore[arg-type]
    ),
)
def test_execution_guard_rejects_every_non_default_mode(
    runtime: FakeRuntimeSettings,
) -> None:
    with pytest.raises(UnsafeOrderExecution):
        assert_safe_execution(runtime)


def test_execution_guard_accepts_only_exact_safe_defaults() -> None:
    assert_safe_execution(FakeRuntimeSettings())


async def test_service_checks_runtime_on_every_operation() -> None:
    runtime = FakeRuntimeSettings()
    bundle = service_bundle(runtime=runtime)
    purchased = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="runtime-recheck"),
    )
    runtime.allow_real_purchases = True

    with pytest.raises(UnsafeOrderExecution):
        await bundle.service.get_order(purchased.intent_id)
    with pytest.raises(UnsafeOrderExecution):
        await bundle.service.recover(purchased.intent_id)
    with pytest.raises(UnsafeOrderExecution):
        await bundle.service.deliver(purchased.intent_id)
    assert bundle.delivery.calls == 0
    assert bundle.supplier.purchase_calls == 1


async def test_unsafe_runtime_cannot_read_catalog_persist_or_dispatch() -> None:
    bundle = service_bundle(runtime=FakeRuntimeSettings(supplier_mode="live"))
    with pytest.raises(UnsafeOrderExecution):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key="unsafe-never-runs"),
        )
    assert bundle.supplier.purchase_calls == 0


async def test_runtime_flip_during_catalog_read_is_rechecked_before_persistence() -> None:
    runtime = FakeRuntimeSettings()
    catalog = RuntimeMutatingCatalog(runtime)
    bundle = service_bundle(catalog=catalog, runtime=runtime)
    key = "runtime-flipped-during-read"

    with pytest.raises(UnsafeOrderExecution):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key=key),
        )
    with pytest.raises(OrderNotFound):
        await bundle.repository.get(intent_id_for(key))
    assert bundle.supplier.purchase_calls == 0


def test_unit_order_suite_has_a_hard_socket_and_dns_guard() -> None:
    direct = socket.socket()
    try:
        with pytest.raises(AssertionError, match="outbound network"):
            direct.connect(("127.0.0.1", 9))
    finally:
        direct.close()
    with pytest.raises(AssertionError, match="outbound network"):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(AssertionError, match="outbound network"):
        socket.getaddrinfo("supplier.invalid", 443)


async def test_public_snapshot_contains_no_mapping_or_supplier_identifier() -> None:
    bundle = service_bundle()
    snapshot = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="public-redaction"),
    )
    rendered = repr(snapshot)
    serialized = repr(asdict(snapshot))
    for private_value in (
        "fake-supplier",
        "supplier-learning-pass",
        "supplier-learning-pass-30d",
        "fake-success-reference",
    ):
        assert private_value not in rendered
        assert private_value not in serialized


async def test_order_flow_never_logs_opaque_or_fulfillment_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "secret-fulfillment-material"
    bundle = service_bundle()
    await bundle.service.place_order(
        customer_reference=secret,
        request=request(key=secret),
    )
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in rendered_logs


def test_internal_repr_surfaces_redact_secret_and_fulfillment_material() -> None:
    product = primary_product()
    variant = product.variants[0]
    secret = "secret-fulfillment-material"
    order_request = OrderRequest(
        product_id=product.id,
        variant_id=variant.id,
        quantity=1,
        idempotency_key=secret,
        max_unit_price=MinorMoney(49_000, "VND", "minor"),
    )
    payload = CanonicalPurchasePayload(
        customer_reference=secret,
        product_id=product.id,
        variant_id=variant.id,
        quantity=1,
        unit_price=MinorMoney.from_catalog(variant.price),
        max_unit_price=order_request.max_unit_price,
        supplier_code="fake-supplier",
        supplier_product_id=secret,
        supplier_variant_id=secret,
    )
    aggregate = build_prepared_order(
        customer_reference=secret,
        request=order_request,
        payload=payload,
    )
    supplier_request = SupplierPurchaseRequest(
        request_key=aggregate.supplier_attempt.request_key,
        payload=payload,
    )

    for value in (
        order_request,
        payload,
        aggregate.intent,
        aggregate.supplier_attempt,
        aggregate,
        supplier_request,
    ):
        assert secret not in repr(value)


def test_existing_catalog_supplier_write_capabilities_remain_disabled() -> None:
    capabilities = FakeCatalogReader.capabilities
    for capability in (
        capabilities.purchase,
        capabilities.payment,
        capabilities.top_up,
        capabilities.refund,
        capabilities.delivery,
    ):
        assert capability.status is CapabilityStatus.DISABLED
