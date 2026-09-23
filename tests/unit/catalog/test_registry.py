"""Catalog source selection stays explicit and fail-closed."""

import pytest

from nyan_shop_bot.catalog.mock import (
    FakeCatalogReader,
    FakeCatalogScenario,
    fake_catalog_scenarios,
)
from nyan_shop_bot.catalog.models import (
    AggregateCatalogState,
    CapabilityStatus,
    CatalogResponse,
    CatalogState,
    LiveCatalogSupplier,
)
from nyan_shop_bot.catalog.registry import (
    CatalogRegistry,
    CatalogSourceSelectionRequired,
    CatalogSourceUnavailable,
)


def _live_response(source: LiveCatalogSupplier) -> CatalogResponse:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    mode = "khommo-readonly" if source == "khommo" else "vietshare-readonly"
    items = tuple(
        item.model_copy(update={"supplier": source, "mode": mode}) for item in fresh.items
    )
    return CatalogResponse(
        supplier=source,
        mode=mode,
        state=CatalogState.FRESH,
        freshness=fresh.freshness,
        items=items,
        error=None,
    )


class StaticReader:
    capabilities = FakeCatalogReader.capabilities

    def __init__(self, response: CatalogResponse | None = None) -> None:
        self.response = response
        self.reads = 0

    async def read_catalog(self) -> CatalogResponse:
        self.reads += 1
        if self.response is None:
            raise RuntimeError("private upstream failure")
        return self.response

    async def get_product(self, product_id: str):  # type: ignore[no-untyped-def]
        return await FakeCatalogReader().get_product(product_id)


def test_single_source_registry_preserves_backward_compatible_default() -> None:
    reader = FakeCatalogReader()
    registry = CatalogRegistry({"mock": reader})

    assert registry.sources == ("mock",)
    assert registry.selection_required is False
    assert registry.resolve() is reader
    assert registry.source_response.model_dump(mode="json") == {
        "sources": [{"supplier": "mock", "mode": "mock", "read_only": True}],
        "selection_required": False,
        "aggregate_available": False,
    }


def test_multi_source_registry_requires_an_available_explicit_source() -> None:
    khommo = FakeCatalogReader()
    vietshare = FakeCatalogReader()
    registry = CatalogRegistry({"khommo": khommo, "vietshare": vietshare})

    assert registry.sources == ("khommo", "vietshare")
    assert registry.selection_required is True
    assert registry.aggregate_available is True
    assert registry.resolve("khommo") is khommo
    assert registry.resolve("vietshare") is vietshare
    with pytest.raises(CatalogSourceSelectionRequired):
        registry.resolve()
    with pytest.raises(CatalogSourceUnavailable):
        registry.resolve("mock")
    assert registry.source_response.aggregate_available is True


async def test_aggregate_interleaves_sources_without_deduplicating_equal_ids() -> None:
    khommo = StaticReader(_live_response("khommo"))
    vietshare = StaticReader(_live_response("vietshare"))
    registry = CatalogRegistry({"khommo": khommo, "vietshare": vietshare})

    response = await registry.read_aggregate()

    assert response.state is AggregateCatalogState.COMPLETE
    assert response.partial is False
    assert response.omitted_count == 0
    assert [(item.supplier, item.id) for item in response.items[:4]] == [
        ("khommo", "learning-pass"),
        ("vietshare", "learning-pass"),
        ("khommo", "design-seat"),
        ("vietshare", "design-seat"),
    ]
    assert [report.item_count for report in response.sources] == [3, 3]
    assert khommo.reads == 1
    assert vietshare.reads == 1


async def test_aggregate_marks_one_failed_source_partial_without_exposing_exception() -> None:
    registry = CatalogRegistry(
        {
            "khommo": StaticReader(_live_response("khommo")),
            "vietshare": StaticReader(),
        }
    )

    response = await registry.read_aggregate()

    assert response.state is AggregateCatalogState.PARTIAL
    assert response.partial is True
    assert {item.supplier for item in response.items} == {"khommo"}
    failed = next(report for report in response.sources if report.supplier == "vietshare")
    assert failed.state is CatalogState.ERROR
    assert failed.error is not None
    assert "private upstream failure" not in failed.error.message


async def test_aggregate_rejects_a_reader_response_claiming_the_wrong_source() -> None:
    registry = CatalogRegistry(
        {
            "khommo": StaticReader(_live_response("vietshare")),
            "vietshare": StaticReader(_live_response("vietshare")),
        }
    )

    response = await registry.read_aggregate()

    assert response.state is AggregateCatalogState.PARTIAL
    assert {item.supplier for item in response.items} == {"vietshare"}
    khommo = next(report for report in response.sources if report.supplier == "khommo")
    assert khommo.state is CatalogState.ERROR


def test_aggregate_capabilities_keep_every_write_operation_disabled() -> None:
    registry = CatalogRegistry(
        {
            "khommo": StaticReader(_live_response("khommo")),
            "vietshare": StaticReader(_live_response("vietshare")),
        }
    )

    capabilities = registry.aggregate_capabilities

    assert capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert capabilities.catalog_detail.status is CapabilityStatus.ENABLED
    assert all(
        capability.status is CapabilityStatus.DISABLED
        for capability in (
            capabilities.purchase,
            capabilities.payment,
            capabilities.top_up,
            capabilities.refund,
            capabilities.delivery,
        )
    )


def test_multi_source_registry_rejects_a_hidden_default() -> None:
    with pytest.raises(ValueError, match="cannot guess a default"):
        CatalogRegistry(
            {"khommo": FakeCatalogReader(), "vietshare": FakeCatalogReader()},
            default_source="khommo",
        )
