"""Synthetic builders shared by the order unit tests."""

from __future__ import annotations

from dataclasses import dataclass

from nyan_shop_bot.catalog.mock import (
    FakeCatalogReader,
    FakeCatalogScenario,
    fake_catalog_scenarios,
)
from nyan_shop_bot.catalog.models import (
    CatalogDetailFound,
    CatalogDetailResponse,
    CatalogProduct,
    CatalogResponse,
    CatalogState,
    CatalogVariant,
    PendingMappingApproval,
    SupplierMapping,
)
from nyan_shop_bot.orders.fakes import (
    FakeDeliverySink,
    FakeRuntimeSettings,
    FakeSupplierPort,
    InMemoryOrderRepository,
)
from nyan_shop_bot.orders.models import (
    CanonicalPurchasePayload,
    MinorMoney,
    OrderAggregate,
    OrderRequest,
    build_prepared_order,
)
from nyan_shop_bot.orders.service import OrderService


class StubCatalogReader:
    """Exact response/detail pair with observable calls and no external I/O."""

    def __init__(
        self,
        *,
        response: CatalogResponse,
        detail: CatalogDetailResponse | None = None,
        read_error: Exception | None = None,
        detail_error: Exception | None = None,
    ) -> None:
        self.capabilities = FakeCatalogReader.capabilities
        self.response = response
        self.detail = detail
        self.read_error = read_error
        self.detail_error = detail_error
        self.read_calls = 0
        self.detail_calls = 0

    async def read_catalog(self) -> CatalogResponse:
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return self.response

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        self.detail_calls += 1
        if self.detail_error is not None:
            raise self.detail_error
        if self.detail is not None:
            return self.detail
        product = next(item for item in self.response.items if item.id == product_id)
        return CatalogDetailFound(state="found", item=product)


@dataclass(slots=True)
class ServiceBundle:
    service: OrderService
    repository: InMemoryOrderRepository
    supplier: FakeSupplierPort
    delivery: FakeDeliverySink
    runtime: FakeRuntimeSettings


def fresh_response() -> CatalogResponse:
    return fake_catalog_scenarios()[FakeCatalogScenario.FRESH]


def primary_product() -> CatalogProduct:
    return fresh_response().items[0]


def response_with_product(product: CatalogProduct) -> CatalogResponse:
    source = fresh_response()
    return CatalogResponse(
        mode="mock",
        state=CatalogState.FRESH,
        freshness=source.freshness,
        items=(product,),
        error=None,
    )


def pending_product() -> CatalogProduct:
    product = primary_product()
    variant = product.variants[0]
    pending_mapping = SupplierMapping(
        supplier_product=variant.mapping.supplier_product,
        supplier_variant=variant.mapping.supplier_variant,
        approval=PendingMappingApproval(status="pending"),
    )
    pending_variant = CatalogVariant(
        id=variant.id,
        name=variant.name,
        mapping=pending_mapping,
        price=variant.price,
        available_quantity=variant.available_quantity,
    )
    return CatalogProduct(
        id=product.id,
        name=product.name,
        description=product.description,
        price=pending_variant.price,
        available_quantity=pending_variant.available_quantity,
        variants=(pending_variant,),
    )


def request(
    *,
    key: str = "opaque-order-key",
    quantity: int = 1,
    cap: int = 49_000,
    currency: str = "VND",
    unit: str = "minor",
    product_id: str = "learning-pass",
    variant_id: str = "learning-pass-30d",
) -> OrderRequest:
    return OrderRequest(
        product_id=product_id,
        variant_id=variant_id,
        quantity=quantity,
        idempotency_key=key,
        max_unit_price=MinorMoney(
            amount_minor=cap,
            currency=currency,
            unit=unit,
        ),
    )


def service_bundle(
    *,
    catalog: StubCatalogReader | None = None,
    repository: InMemoryOrderRepository | None = None,
    supplier: FakeSupplierPort | None = None,
    delivery: FakeDeliverySink | None = None,
    runtime: FakeRuntimeSettings | None = None,
) -> ServiceBundle:
    actual_repository = repository or InMemoryOrderRepository()
    actual_supplier = supplier or FakeSupplierPort()
    actual_delivery = delivery or FakeDeliverySink()
    actual_runtime = runtime or FakeRuntimeSettings()
    actual_catalog = catalog or StubCatalogReader(response=fresh_response())
    return ServiceBundle(
        service=OrderService(
            catalog=actual_catalog,
            repository=actual_repository,
            supplier=actual_supplier,
            delivery_sink=actual_delivery,
            runtime=actual_runtime,
        ),
        repository=actual_repository,
        supplier=actual_supplier,
        delivery=actual_delivery,
        runtime=actual_runtime,
    )


def prepared_candidate(
    *,
    key: str = "opaque-crash-key",
    quantity: int = 1,
) -> OrderAggregate:
    order_request = request(key=key, quantity=quantity)
    product = primary_product()
    variant = product.variants[0]
    mapping = variant.mapping
    payload = CanonicalPurchasePayload(
        customer_reference="synthetic-customer",
        product_id=product.id,
        variant_id=variant.id,
        quantity=quantity,
        unit_price=MinorMoney.from_catalog(variant.price),
        max_unit_price=order_request.max_unit_price,
        supplier_code=mapping.supplier_product.supplier_id,
        supplier_product_id=mapping.supplier_product.supplier_product_id,
        supplier_variant_id=mapping.supplier_variant.supplier_variant_id,
    )
    return build_prepared_order(
        customer_reference="synthetic-customer",
        request=order_request,
        payload=payload,
    )
