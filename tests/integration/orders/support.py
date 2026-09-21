"""Synthetic order builders for PostgreSQL integration tests."""

from __future__ import annotations

from nyan_shop_bot.catalog.mock import FakeCatalogReader, FakeCatalogScenario
from nyan_shop_bot.orders.fakes import (
    FakeDeliverySink,
    FakeRuntimeSettings,
    FakeSupplierPort,
)
from nyan_shop_bot.orders.models import (
    CanonicalPurchasePayload,
    MinorMoney,
    OrderAggregate,
    OrderRequest,
    build_prepared_order,
)
from nyan_shop_bot.orders.ports import DeliverySink, PurchasePort
from nyan_shop_bot.orders.repository import PostgresOrderRepository
from nyan_shop_bot.orders.service import OrderService


def request(
    *,
    key: str,
    quantity: int = 1,
    cap: int = 49_000,
) -> OrderRequest:
    return OrderRequest(
        product_id="learning-pass",
        variant_id="learning-pass-30d",
        quantity=quantity,
        idempotency_key=key,
        max_unit_price=MinorMoney(cap, "VND", "minor"),
    )


def prepared_candidate(
    *,
    key: str,
    quantity: int = 1,
    cap: int = 49_000,
) -> OrderAggregate:
    order_request = request(key=key, quantity=quantity, cap=cap)
    payload = CanonicalPurchasePayload(
        customer_reference="synthetic-customer",
        product_id=order_request.product_id,
        variant_id=order_request.variant_id,
        quantity=quantity,
        unit_price=MinorMoney(49_000, "VND", "minor"),
        max_unit_price=order_request.max_unit_price,
        supplier_code="fake-supplier",
        supplier_product_id="supplier-learning-pass",
        supplier_variant_id="supplier-learning-pass-30d",
    )
    return build_prepared_order(
        customer_reference="synthetic-customer",
        request=order_request,
        payload=payload,
    )


def service(
    repository: PostgresOrderRepository,
    *,
    supplier: PurchasePort | None = None,
    delivery: DeliverySink | None = None,
) -> OrderService:
    return OrderService(
        catalog=FakeCatalogReader(FakeCatalogScenario.FRESH),
        repository=repository,
        supplier=supplier or FakeSupplierPort(),
        delivery_sink=delivery or FakeDeliverySink(),
        runtime=FakeRuntimeSettings(),
    )
