"""Fresh catalog and server-authority gates must all precede persistence."""

from __future__ import annotations

import pytest

from nyan_shop_bot.catalog.mock import FakeCatalogScenario, fake_catalog_scenarios
from nyan_shop_bot.catalog.models import (
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogDetailUnsupported,
    CatalogError,
    CatalogErrorCode,
    CatalogProduct,
)
from nyan_shop_bot.orders.errors import (
    CatalogDetailRejected,
    CatalogNotFresh,
    CatalogReadRejected,
    CatalogSnapshotMismatch,
    MappingNotApproved,
    MoneyMismatch,
    OrderNotFound,
    PriceCapExceeded,
    ProductUnavailable,
    QuantityUnavailable,
    SupplierMappingMismatch,
    VariantUnavailable,
)
from nyan_shop_bot.orders.fakes import FakeSupplierPort
from nyan_shop_bot.orders.models import OrderRequest, PurchaseState, intent_id_for
from tests.unit.orders.support import (
    ServiceBundle,
    StubCatalogReader,
    fresh_response,
    pending_product,
    primary_product,
    request,
    response_with_product,
    service_bundle,
)


async def _assert_not_persisted(bundle: ServiceBundle, key: str) -> None:
    repository = bundle.repository
    with pytest.raises(OrderNotFound):
        await repository.get(intent_id_for(key))


@pytest.mark.parametrize(
    "scenario",
    (
        FakeCatalogScenario.STALE,
        FakeCatalogScenario.EMPTY,
        FakeCatalogScenario.ERROR,
    ),
)
async def test_non_fresh_catalog_states_create_no_intent(
    scenario: FakeCatalogScenario,
) -> None:
    key = f"catalog-{scenario.value}"
    catalog = StubCatalogReader(response=fake_catalog_scenarios()[scenario])
    bundle = service_bundle(catalog=catalog)

    with pytest.raises(CatalogNotFresh):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key=key),
        )

    assert catalog.detail_calls == 0
    assert bundle.supplier.purchase_calls == 0
    await _assert_not_persisted(bundle, key)


async def test_catalog_read_exception_is_sanitized_before_persistence() -> None:
    key = "catalog-read-error"
    catalog = StubCatalogReader(
        response=fresh_response(),
        read_error=RuntimeError("upstream-secret-body"),
    )
    bundle = service_bundle(catalog=catalog)

    with pytest.raises(CatalogReadRejected) as caught:
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key=key),
        )
    assert "upstream-secret-body" not in str(caught.value)
    await _assert_not_persisted(bundle, key)


async def test_unknown_product_and_variant_are_safe_pre_persistence_rejections() -> None:
    bundle = service_bundle()
    with pytest.raises(ProductUnavailable):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key="unknown-product", product_id="unknown-product"),
        )
    with pytest.raises(VariantUnavailable):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key="unknown-variant", variant_id="unknown-variant"),
        )
    assert bundle.supplier.purchase_calls == 0


@pytest.mark.parametrize("detail_kind", ("not_found", "unsupported", "exception"))
async def test_detail_must_be_found_and_authoritative(detail_kind: str) -> None:
    product = primary_product()
    if detail_kind == "not_found":
        detail = CatalogDetailNotFound(state="not_found", product_id=product.id)
        detail_error = None
    elif detail_kind == "unsupported":
        detail = CatalogDetailUnsupported(
            state="unsupported",
            product_id=product.id,
            error=CatalogError(
                code=CatalogErrorCode.UNSUPPORTED,
                message="Synthetic detail is unsupported.",
                retryable=False,
            ),
        )
        detail_error = None
    else:
        detail = None
        detail_error = RuntimeError("supplier-secret-detail")
    catalog = StubCatalogReader(
        response=response_with_product(product),
        detail=detail,
        detail_error=detail_error,
    )
    bundle = service_bundle(catalog=catalog)

    with pytest.raises(CatalogDetailRejected) as caught:
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key=f"detail-{detail_kind}"),
        )
    assert "supplier-secret-detail" not in str(caught.value)
    assert bundle.supplier.purchase_calls == 0


async def test_detail_must_exactly_equal_the_fresh_listing_snapshot() -> None:
    listing = primary_product()
    changed_detail = CatalogProduct(
        id=listing.id,
        name="Changed after listing",
        description=listing.description,
        price=listing.price,
        available_quantity=listing.available_quantity,
        variants=listing.variants,
    )
    catalog = StubCatalogReader(
        response=response_with_product(listing),
        detail=CatalogDetailFound(state="found", item=changed_detail),
    )
    bundle = service_bundle(catalog=catalog)

    with pytest.raises(CatalogSnapshotMismatch):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key="detail-mismatch"),
        )
    assert bundle.supplier.purchase_calls == 0


async def test_pending_mapping_is_rejected_before_persistence_or_dispatch() -> None:
    product = pending_product()
    catalog = StubCatalogReader(response=response_with_product(product))
    bundle = service_bundle(catalog=catalog)
    key = "pending-mapping"

    with pytest.raises(MappingNotApproved):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key=key),
        )
    assert bundle.supplier.purchase_calls == 0
    await _assert_not_persisted(bundle, key)


async def test_mapping_must_match_the_injected_fake_supplier() -> None:
    supplier = FakeSupplierPort(supplier_code="different-fake-supplier")
    bundle = service_bundle(supplier=supplier)
    key = "mismatched-mapping"
    with pytest.raises(SupplierMappingMismatch):
        await bundle.service.place_order(
            customer_reference="synthetic-customer",
            request=request(key=key),
        )
    assert supplier.purchase_calls == 0
    await _assert_not_persisted(bundle, key)


async def test_server_price_and_client_cap_are_separate_authorities() -> None:
    bundle = service_bundle()
    snapshot = await bundle.service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="server-price", cap=60_000),
    )
    stored = await bundle.repository.get(snapshot.intent_id)

    assert snapshot.purchase_state is PurchaseState.SUCCEEDED
    assert snapshot.unit_price.amount_minor == 49_000
    assert snapshot.max_unit_price.amount_minor == 60_000
    assert stored.intent.unit_price.amount_minor == 49_000
    assert stored.intent.max_unit_price.amount_minor == 60_000
    assert stored.supplier_attempt.request_payload.unit_price.amount_minor == 49_000


async def test_currency_mismatch_price_cap_and_stock_fail_before_persistence() -> None:
    cases = (
        (MoneyMismatch, request(key="money-mismatch", currency="USD")),
        (PriceCapExceeded, request(key="cap-too-low", cap=48_999)),
        (QuantityUnavailable, request(key="stock-too-low", quantity=13)),
    )
    for error_type, order_request in cases:
        bundle = service_bundle()
        with pytest.raises(error_type):
            await bundle.service.place_order(
                customer_reference="synthetic-customer",
                request=order_request,
            )
        assert bundle.supplier.purchase_calls == 0
        await _assert_not_persisted(bundle, order_request.idempotency_key)


def test_client_cannot_supply_product_name_mapping_or_current_price() -> None:
    values = {
        "product_id": "learning-pass",
        "variant_id": "learning-pass-30d",
        "quantity": 1,
        "idempotency_key": "forged-fields",
        "max_unit_price": request().max_unit_price,
        "product_name": "forged name",
        "current_price": 1,
        "supplier_mapping": "forged mapping",
    }
    with pytest.raises(TypeError):
        OrderRequest(**values)  # type: ignore[arg-type]
