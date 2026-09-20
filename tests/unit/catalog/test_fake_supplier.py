"""Determinism and safety tests for the synthetic supplier."""

from nyan_shop_bot.catalog.mock import (
    FakeCatalogReader,
    FakeCatalogScenario,
    fake_catalog_scenarios,
)
from nyan_shop_bot.catalog.models import (
    CapabilityStatus,
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogState,
)


def test_all_fake_scenarios_are_deterministic_and_complete() -> None:
    first = {
        name.value: response.model_dump_json()
        for name, response in fake_catalog_scenarios().items()
    }
    second = {
        name.value: response.model_dump_json()
        for name, response in fake_catalog_scenarios().items()
    }

    assert first == second
    assert set(first) == {"fresh", "stale", "empty", "error"}


async def test_fake_supplier_preserves_product_and_variant_identities() -> None:
    catalog = await FakeCatalogReader().read_catalog()

    assert catalog.state is CatalogState.FRESH
    assert len(catalog.items) == 3
    for product in catalog.items:
        for variant in product.variants:
            assert variant.mapping.is_approved
            assert variant.mapping.supplier_product.supplier_id == "fake-supplier"
            assert variant.mapping.supplier_variant.supplier_id == "fake-supplier"
            assert (
                variant.mapping.supplier_product.supplier_product_id
                != variant.mapping.supplier_variant.supplier_variant_id
            )


async def test_fake_supplier_looks_up_normalized_id_not_display_name() -> None:
    supplier = FakeCatalogReader()

    found = await supplier.get_product("learning-pass")
    by_name = await supplier.get_product("Synthetic learning pass")

    assert isinstance(found, CatalogDetailFound)
    assert found.item.id == "learning-pass"
    assert isinstance(by_name, CatalogDetailNotFound)


async def test_fake_supplier_can_emit_each_validated_ui_state() -> None:
    for scenario in FakeCatalogScenario:
        response = await FakeCatalogReader(scenario).read_catalog()
        assert response.state.value == scenario.value


def test_fake_supplier_has_no_money_or_delivery_operations() -> None:
    supplier = FakeCatalogReader()
    capabilities = supplier.capabilities

    assert capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert capabilities.catalog_detail.status is CapabilityStatus.ENABLED
    assert {
        capabilities.purchase.status,
        capabilities.payment.status,
        capabilities.top_up.status,
        capabilities.refund.status,
        capabilities.delivery.status,
    } == {CapabilityStatus.DISABLED}
    for operation in (
        "order",
        "purchase",
        "payment",
        "pay",
        "top_up",
        "topup",
        "refund",
        "delivery",
        "deliver",
    ):
        assert not hasattr(supplier, operation)
