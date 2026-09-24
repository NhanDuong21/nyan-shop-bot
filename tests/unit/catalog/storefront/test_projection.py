"""Customer-safe projection tests over persisted curation and synthetic reads."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationDocument,
    CatalogCurationListing,
    CatalogCurationOfferRef,
)
from nyan_shop_bot.catalog.curation.repository import InMemoryCatalogCurationRepository
from nyan_shop_bot.catalog.curation.service import CatalogCurationService
from nyan_shop_bot.catalog.mock import (
    FakeCatalogReader,
    FakeCatalogScenario,
    fake_catalog_scenarios,
)
from nyan_shop_bot.catalog.models import (
    CatalogDetailResponse,
    CatalogProduct,
    CatalogResponse,
    CatalogState,
    CatalogSupplier,
    Money,
)
from nyan_shop_bot.catalog.registry import CatalogRegistry
from nyan_shop_bot.catalog.storefront.models import (
    StorefrontAvailability,
    StorefrontCatalogResponse,
    StorefrontCatalogState,
    StorefrontProduct,
)


class LiveReader:
    capabilities = FakeCatalogReader.capabilities

    def __init__(self, supplier: CatalogSupplier, products: tuple[CatalogProduct, ...]) -> None:
        self.supplier = supplier
        self.products = products
        self.catalog_reads = 0

    async def read_catalog(self) -> CatalogResponse:
        self.catalog_reads += 1
        fixture = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
        mode = "khommo-readonly" if self.supplier == "khommo" else "vietshare-readonly"
        return CatalogResponse(
            supplier=self.supplier,
            mode=mode,
            state=CatalogState.FRESH,
            freshness=fixture.freshness,
            items=tuple(
                product.model_copy(update={"supplier": self.supplier, "mode": mode})
                for product in self.products
            ),
            error=None,
        )

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        return await FakeCatalogReader().get_product(product_id)


class FailingLiveReader(LiveReader):
    async def read_catalog(self) -> CatalogResponse:
        self.catalog_reads += 1
        raise RuntimeError("private upstream body must never reach the storefront")


def ref(supplier: str, product_id: str) -> CatalogCurationOfferRef:
    return CatalogCurationOfferRef(  # type: ignore[arg-type]
        supplier=supplier,
        supplier_product_id=product_id,
    )


def listing(
    *,
    listing_id: str,
    sort_order: int,
    offer_ref: CatalogCurationOfferRef,
    visible: bool = True,
    name: str = "Sản phẩm Nyan",
    priced: bool = True,
) -> CatalogCurationListing:
    return CatalogCurationListing(
        id=listing_id,
        name=name,
        description="Mô tả do chủ shop biên tập.",
        category="Tiện ích",
        visible=visible,
        sort_order=sort_order,
        retail_price=(Money(amount_minor=30_000, currency="VND", unit="minor") if priced else None),
        offer_refs=(offer_ref,),
    )


def subject(
    document: CatalogCurationDocument,
    *,
    failing: bool = False,
) -> tuple[CatalogCurationService, LiveReader, LiveReader]:
    fixture = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    reader_type = FailingLiveReader if failing else LiveReader
    khommo = reader_type("khommo", (fixture.items[0], fixture.items[2]))
    vietshare = reader_type("vietshare", (fixture.items[1],))
    return (
        CatalogCurationService(
            catalogs=CatalogRegistry({"khommo": khommo, "vietshare": vietshare}),
            repository=InMemoryCatalogCurationRepository(document),
        ),
        khommo,
        vietshare,
    )


async def test_projection_orders_visible_listings_and_derives_conservative_stock() -> None:
    document = CatalogCurationDocument(
        revision=7,
        listings=(
            listing(
                listing_id="sold-out",
                sort_order=1,
                offer_ref=ref("khommo", "toolkit"),
            ),
            listing(
                listing_id="available",
                sort_order=0,
                offer_ref=ref("khommo", "learning-pass"),
                name="KhoMMO và VietShare do Nyan biên tập",
            ),
            listing(
                listing_id="unknown",
                sort_order=2,
                offer_ref=ref("vietshare", "missing-product"),
            ),
            listing(
                listing_id="hidden",
                sort_order=3,
                offer_ref=ref("vietshare", "design-seat"),
                visible=False,
                priced=False,
            ),
        ),
    )
    service, _, _ = subject(document)

    response = await service.read_storefront()

    assert response.revision == 7
    assert response.state is StorefrontCatalogState.PARTIAL
    assert response.partial is True
    assert response.unresolved_offer_count == 1
    assert [item.id for item in response.items] == ["available", "sold-out", "unknown"]
    assert [item.availability for item in response.items] == [
        StorefrontAvailability.IN_STOCK,
        StorefrontAvailability.OUT_OF_STOCK,
        StorefrontAvailability.UNKNOWN,
    ]
    assert response.items[0].name == "Nyan và Nyan do Nyan biên tập"
    rendered = response.model_dump_json().lower()
    for forbidden in (
        "khommo",
        "vietshare",
        "learning-pass",
        "toolkit",
        "missing-product",
        "available_quantity",
        "mapping",
        "delivery",
        "credential",
    ):
        assert forbidden not in rendered
    assert response.supplier_provenance_exposed is False
    assert response.purchase_enabled is False
    assert response.payment_enabled is False


async def test_detail_uses_same_projection_and_hidden_listing_is_not_found() -> None:
    document = CatalogCurationDocument(
        revision=1,
        listings=(
            listing(
                listing_id="available",
                sort_order=0,
                offer_ref=ref("khommo", "learning-pass"),
            ),
            listing(
                listing_id="hidden",
                sort_order=1,
                offer_ref=ref("vietshare", "design-seat"),
                visible=False,
            ),
        ),
    )
    service, _, _ = subject(document)

    catalog = await service.read_storefront()
    found = await service.get_storefront_product("available")
    hidden = await service.get_storefront_product("hidden")

    assert found.state == "found"
    assert found.item == catalog.items[0]
    assert hidden.state == "not_found"


async def test_empty_storefront_does_not_contact_live_readers() -> None:
    service, khommo, vietshare = subject(CatalogCurationDocument(revision=0, listings=()))

    response = await service.read_storefront()

    assert response.state is StorefrontCatalogState.EMPTY
    assert response.items == ()
    assert khommo.catalog_reads == 0
    assert vietshare.catalog_reads == 0


async def test_complete_source_outage_keeps_listing_with_unknown_availability() -> None:
    document = CatalogCurationDocument(
        revision=2,
        listings=(
            listing(
                listing_id="safe-listing",
                sort_order=0,
                offer_ref=ref("khommo", "learning-pass"),
            ),
        ),
    )
    service, _, _ = subject(document, failing=True)

    response = await service.read_storefront()

    assert response.state is StorefrontCatalogState.PARTIAL
    assert response.source_evidence_partial is True
    assert response.unresolved_offer_count == 1
    assert response.items[0].availability is StorefrontAvailability.UNKNOWN
    assert "private upstream" not in response.model_dump_json().lower()


def test_storefront_contract_rejects_non_vnd_and_inconsistent_state() -> None:
    with pytest.raises(ValidationError, match="VND"):
        StorefrontProduct(
            id="invalid-currency",
            name="Tên",
            description="Mô tả",
            category=None,
            price=Money(amount_minor=10, currency="USD", unit="minor"),
            availability=StorefrontAvailability.IN_STOCK,
        )

    with pytest.raises(ValidationError, match="partial"):
        StorefrontCatalogResponse(
            revision=1,
            state=StorefrontCatalogState.READY,
            items=(
                StorefrontProduct(
                    id="valid",
                    name="Tên",
                    description="Mô tả",
                    category=None,
                    price=Money(amount_minor=10, currency="VND", unit="minor"),
                    availability=StorefrontAvailability.IN_STOCK,
                ),
            ),
            partial=True,
            unresolved_offer_count=1,
            source_evidence_partial=False,
        )
