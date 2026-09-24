"""Application tests for explicit grouping over read-only catalog snapshots."""

import asyncio

import pytest

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationListingInput,
    CatalogCurationOfferRef,
    CatalogCurationSaveRequest,
)
from nyan_shop_bot.catalog.curation.ports import CatalogCurationRevisionConflict
from nyan_shop_bot.catalog.curation.repository import InMemoryCatalogCurationRepository
from nyan_shop_bot.catalog.curation.service import (
    CatalogCurationService,
    UnknownCatalogOffer,
    decode_offer_key,
    encode_offer_key,
)
from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.catalog.models import (
    CatalogDetailResponse,
    CatalogResponse,
    CatalogState,
    CatalogSupplier,
    Money,
)
from nyan_shop_bot.catalog.registry import CatalogRegistry


class LiveReader:
    capabilities = FakeCatalogReader.capabilities

    def __init__(self, supplier: CatalogSupplier) -> None:
        self._supplier = supplier
        self._delegate = FakeCatalogReader()
        self.catalog_reads = 0

    async def read_catalog(self) -> CatalogResponse:
        self.catalog_reads += 1
        response = await self._delegate.read_catalog()
        mode = "khommo-readonly" if self._supplier == "khommo" else "vietshare-readonly"
        return CatalogResponse(
            supplier=self._supplier,
            mode=mode,
            state=CatalogState.FRESH,
            freshness=response.freshness,
            items=tuple(
                item.model_copy(update={"supplier": self._supplier, "mode": mode})
                for item in response.items[:1]
            ),
            error=None,
        )

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        return await self._delegate.get_product(product_id)


class FailingLiveReader(LiveReader):
    async def read_catalog(self) -> CatalogResponse:
        self.catalog_reads += 1
        raise RuntimeError("synthetic read-only catalog outage")


def service() -> tuple[
    CatalogCurationService,
    InMemoryCatalogCurationRepository,
    LiveReader,
    LiveReader,
]:
    khommo = LiveReader("khommo")
    vietshare = LiveReader("vietshare")
    repository = InMemoryCatalogCurationRepository()
    return (
        CatalogCurationService(
            catalogs=CatalogRegistry({"khommo": khommo, "vietshare": vietshare}),
            repository=repository,
        ),
        repository,
        khommo,
        vietshare,
    )


def listing_input(key: str) -> CatalogCurationListingInput:
    return CatalogCurationListingInput(
        id="nyan-learning",
        name="Gói học tập Nyan",
        description="Mô tả dành cho khách hàng.",
        category="Học tập",
        visible=True,
        sort_order=0,
        retail_price=Money(amount_minor=125_000, currency="VND", unit="minor"),
        offer_keys=(key,),
    )


def test_offer_key_round_trip_is_canonical_and_source_qualified() -> None:
    ref = CatalogCurationOfferRef(
        supplier="vietshare",
        supplier_product_id="mã/sản-phẩm:1",
    )
    key = encode_offer_key(ref)

    assert decode_offer_key(key) == ref
    with pytest.raises(UnknownCatalogOffer):
        decode_offer_key("vietshare.not canonical!")


async def test_workspace_and_save_keep_grouping_explicit_and_read_only() -> None:
    subject, _, khommo, vietshare = service()

    initial = await subject.get_workspace()
    assert len(initial.offers) == 2
    assert {offer.supplier for offer in initial.offers} == {"khommo", "vietshare"}
    assert all(offer.read_only for offer in initial.offers)
    assert initial.supplier_writes_enabled is False
    assert initial.listings == ()

    selected = next(offer for offer in initial.offers if offer.supplier == "khommo")
    saved = await subject.save_workspace(
        CatalogCurationSaveRequest(
            expected_revision=0,
            listings=(listing_input(selected.key),),
        )
    )

    assert saved.revision == 1
    assert saved.listings[0].offer_keys == (selected.key,)
    assigned_offer = next(offer for offer in saved.offers if offer.key == selected.key)
    assert assigned_offer.assigned_listing_id == "nyan-learning"
    assert khommo.catalog_reads == 2
    assert vietshare.catalog_reads == 2
    rendered = saved.model_dump_json()
    assert "credential" not in rendered
    assert "delivery" not in rendered


async def test_complete_source_outage_remains_explicitly_degraded() -> None:
    khommo = FailingLiveReader("khommo")
    vietshare = FailingLiveReader("vietshare")
    subject = CatalogCurationService(
        catalogs=CatalogRegistry({"khommo": khommo, "vietshare": vietshare}),
        repository=InMemoryCatalogCurationRepository(),
    )

    workspace = await subject.get_workspace()

    assert workspace.offers == ()
    assert workspace.listings == ()
    assert workspace.source_partial is True
    assert workspace.supplier_writes_enabled is False
    assert khommo.catalog_reads == 1
    assert vietshare.catalog_reads == 1


async def test_unknown_snapshot_offer_and_stale_revision_fail_closed() -> None:
    subject, repository, _, _ = service()
    unknown = encode_offer_key(
        CatalogCurationOfferRef(
            supplier="khommo",
            supplier_product_id="not-in-current-snapshot",
        )
    )

    with pytest.raises(UnknownCatalogOffer, match="absent"):
        await subject.save_workspace(
            CatalogCurationSaveRequest(
                expected_revision=0,
                listings=(listing_input(unknown),),
            )
        )

    snapshot = await subject.get_workspace()
    key = snapshot.offers[0].key
    request = CatalogCurationSaveRequest(
        expected_revision=0,
        listings=(listing_input(key),),
    )
    results = await asyncio.gather(
        subject.save_workspace(request),
        subject.save_workspace(request),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, CatalogCurationRevisionConflict) for result in results) == 1
    assert (await repository.load()).revision == 1
