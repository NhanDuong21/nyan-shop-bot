"""In-process API contract tests."""

from httpx import ASGITransport, AsyncClient

from nyan_shop_bot.catalog.mock import FakeCatalogReader, FakeCatalogScenario
from nyan_shop_bot.catalog.models import (
    CatalogDetailFound,
    CatalogDetailResponse,
    CatalogResponse,
    CatalogState,
    CatalogSupplier,
)
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.catalog.registry import CatalogRegistry
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import build_catalog_reader, build_catalog_registry, create_app
from nyan_shop_bot.suppliers.khommo import KhoMmoCatalogReader
from nyan_shop_bot.suppliers.vietshare import VietShareCatalogReader


class ReadyDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class CountingCatalogReader:
    capabilities = FakeCatalogReader.capabilities

    def __init__(self, source: CatalogSupplier = "mock") -> None:
        self.delegate = FakeCatalogReader()
        self.source = source
        self.catalog_reads = 0
        self.product_reads: list[str] = []

    async def read_catalog(self) -> CatalogResponse:
        self.catalog_reads += 1
        response = await self.delegate.read_catalog()
        if self.source == "mock":
            return response
        mode = "khommo-readonly" if self.source == "khommo" else "vietshare-readonly"
        return CatalogResponse(
            supplier=self.source,
            mode=mode,
            state=CatalogState.FRESH,
            freshness=response.freshness,
            items=tuple(
                item.model_copy(update={"supplier": self.source, "mode": mode})
                for item in response.items
            ),
            error=None,
        )

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        self.product_reads.append(product_id)
        response = await self.delegate.get_product(product_id)
        if self.source == "mock" or not isinstance(response, CatalogDetailFound):
            return response
        mode = "khommo-readonly" if self.source == "khommo" else "vietshare-readonly"
        return CatalogDetailFound(
            state="found",
            item=response.item.model_copy(update={"supplier": self.source, "mode": mode}),
        )


def make_client(catalog: CatalogReader | None = None) -> AsyncClient:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    application = create_app(settings=settings, catalog=catalog, database=ReadyDatabase())
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


async def test_health_exposes_safety_state() -> None:
    async with make_client() as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "supplier_mode": "mock",
        "payment_mode": "disabled",
        "allow_real_purchases": False,
        "read_only": True,
    }


async def test_live_read_factory_constructs_khommo_without_contacting_supplier() -> None:
    secret = "local-secret-marker"
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supplier_mode="khommo-readonly",
        khommo_api_token=secret,
        payment_mode="disabled",
        allow_real_purchases=False,
    )

    catalog, close_catalog = build_catalog_reader(settings)
    try:
        assert isinstance(catalog, KhoMmoCatalogReader)
        assert secret not in repr(catalog)
    finally:
        assert close_catalog is not None
        await close_catalog()


async def test_live_read_factory_constructs_vietshare_without_contacting_supplier() -> None:
    api_id = "synthetic-private-id"
    api_secret = "synthetic-private-secret"
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supplier_mode="vietshare-readonly",
        vietshare_api_id=api_id,
        vietshare_api_secret=api_secret,
        payment_mode="disabled",
        allow_real_purchases=False,
    )

    catalog, close_catalog = build_catalog_reader(settings)
    try:
        assert isinstance(catalog, VietShareCatalogReader)
        assert api_id not in repr(catalog)
        assert api_secret not in repr(catalog)
    finally:
        assert close_catalog is not None
        await close_catalog()


async def test_multi_read_factory_constructs_both_sources_without_contacting_them() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supplier_mode="multi-readonly",
        khommo_api_token="synthetic-khommo",
        vietshare_api_id="synthetic-vietshare-id",
        vietshare_api_secret="synthetic-vietshare-secret",
    )

    registry, close_catalog = build_catalog_registry(settings)
    try:
        assert registry.sources == ("khommo", "vietshare")
        assert isinstance(registry.resolve("khommo"), KhoMmoCatalogReader)
        assert isinstance(registry.resolve("vietshare"), VietShareCatalogReader)
    finally:
        assert close_catalog is not None
        await close_catalog()


async def test_multi_read_api_requires_and_routes_explicit_sources() -> None:
    khommo = CountingCatalogReader("khommo")
    vietshare = CountingCatalogReader("vietshare")
    registry = CatalogRegistry({"khommo": khommo, "vietshare": vietshare})
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supplier_mode="multi-readonly",
        khommo_api_token="synthetic-khommo",
        vietshare_api_id="synthetic-vietshare-id",
        vietshare_api_secret="synthetic-vietshare-secret",
    )
    application = create_app(
        settings=settings,
        catalogs=registry,
        database=ReadyDatabase(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        sources = await client.get("/api/v1/catalog/sources")
        missing_source = await client.get("/api/v1/catalog")
        aggregate = await client.get("/api/v1/catalog?source=all")
        khommo_catalog = await client.get("/api/v1/catalog?source=khommo")
        vietshare_detail = await client.get("/api/v1/catalog/learning-pass?source=vietshare")
        vietshare_capabilities = await client.get("/api/v1/capabilities?source=vietshare")
        aggregate_capabilities = await client.get("/api/v1/capabilities?source=all")
        aggregate_detail = await client.get("/api/v1/catalog/learning-pass?source=all")
        unavailable = await client.get("/api/v1/catalog?source=mock")
        invalid = await client.get("/api/v1/catalog?source=roboticvn")

    assert sources.status_code == 200
    assert sources.json() == {
        "sources": [
            {"supplier": "khommo", "mode": "khommo-readonly", "read_only": True},
            {
                "supplier": "vietshare",
                "mode": "vietshare-readonly",
                "read_only": True,
            },
        ],
        "selection_required": True,
        "aggregate_available": True,
    }
    assert missing_source.status_code == 400
    assert missing_source.json()["detail"] == "catalog source selection is required"
    assert aggregate.status_code == 200
    aggregate_body = aggregate.json()
    assert aggregate_body["supplier"] == "aggregate"
    assert aggregate_body["mode"] == "multi-readonly"
    assert aggregate_body["state"] == "complete"
    assert [(item["supplier"], item["id"]) for item in aggregate_body["items"][:4]] == [
        ("khommo", "learning-pass"),
        ("vietshare", "learning-pass"),
        ("khommo", "design-seat"),
        ("vietshare", "design-seat"),
    ]
    assert khommo_catalog.status_code == 200
    assert vietshare_detail.status_code == 200
    assert vietshare_capabilities.status_code == 200
    assert aggregate_capabilities.status_code == 200
    assert aggregate_capabilities.json()["purchase"]["status"] == "disabled"
    assert aggregate_detail.status_code == 422
    assert unavailable.status_code == 404
    assert invalid.status_code == 422
    assert khommo.catalog_reads == 2
    assert vietshare.catalog_reads == 1
    assert vietshare.product_reads == ["learning-pass"]


async def test_live_read_catalog_routes_reject_non_loopback_clients() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="local",
        app_host="127.0.0.1",
        supplier_mode="khommo-readonly",
        khommo_api_token="synthetic-secret",
        payment_mode="disabled",
        allow_real_purchases=False,
    )
    application = create_app(
        settings=settings,
        catalog=FakeCatalogReader(),
        database=ReadyDatabase(),
    )
    remote_transport = ASGITransport(app=application, client=("203.0.113.10", 42000))
    loopback_transport = ASGITransport(app=application, client=("127.0.0.1", 42001))

    async with AsyncClient(transport=remote_transport, base_url="http://test") as client:
        health = await client.get("/healthz")
        blocked = [
            await client.get("/api/v1/catalog/sources"),
            await client.get("/api/v1/catalog"),
            await client.get("/api/v1/catalog/p-1"),
            await client.get("/api/v1/capabilities"),
        ]
    async with AsyncClient(transport=loopback_transport, base_url="http://test") as client:
        capabilities = await client.get("/api/v1/capabilities")

    assert health.status_code == 200
    assert [response.status_code for response in blocked] == [403, 403, 403, 403]
    assert all(
        response.json()["detail"] == "live-read catalog is available only from loopback"
        for response in blocked
    )
    assert capabilities.status_code == 200


async def test_readiness_uses_database_probe() -> None:
    async with make_client() as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_catalog_exposes_normalized_identifiers_money_and_freshness() -> None:
    async with make_client() as client:
        response = await client.get("/api/v1/catalog")

    body = response.json()
    assert response.status_code == 200
    assert body["mode"] == "mock"
    assert body["state"] == "fresh"
    assert body["freshness"]["status"] == "fresh"
    assert body["partial"] is False
    assert body["omitted_count"] == 0
    assert len(body["items"]) == 3

    variants = [variant for item in body["items"] for variant in item["variants"]]
    assert {variant["price"]["currency"] for variant in variants} == {"VND"}
    assert {variant["price"]["unit"] for variant in variants} == {"minor"}
    assert all(isinstance(variant["price"]["amount_minor"], int) for variant in variants)
    assert all(variant["mapping"]["approval"]["status"] == "approved" for variant in variants)
    assert all(
        variant["mapping"]["supplier_product"]["supplier_product_id"]
        != variant["mapping"]["supplier_variant"]["supplier_variant_id"]
        for variant in variants
    )
    assert all(item["supplier"] == "mock" and item["mode"] == "mock" for item in body["items"])
    assert all(item["price"] == item["variants"][0]["price"] for item in body["items"])
    assert all(
        item["available_quantity"] == item["variants"][0]["available_quantity"]
        for item in body["items"]
    )


async def test_catalog_detail_uses_normalized_id_only() -> None:
    async with make_client() as client:
        found = await client.get("/api/v1/catalog/learning-pass")
        display_name = await client.get("/api/v1/catalog/Synthetic%20learning%20pass")

    assert found.status_code == 200
    assert found.json()["state"] == "found"
    assert found.json()["item"]["id"] == "learning-pass"
    assert display_name.status_code == 200
    assert display_name.json() == {
        "state": "not_found",
        "product_id": "Synthetic learning pass",
    }


async def test_catalog_detail_rejects_blank_identifier() -> None:
    async with make_client() as client:
        response = await client.get("/api/v1/catalog/%20")

    assert response.status_code == 422


async def test_catalog_error_is_a_typed_client_state() -> None:
    async with make_client(FakeCatalogReader(FakeCatalogScenario.ERROR)) as client:
        response = await client.get("/api/v1/catalog")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "mock",
        "state": "error",
        "freshness": None,
        "items": [],
        "error": {
            "code": "source_unavailable",
            "message": "The deterministic mock catalog is unavailable.",
            "retryable": True,
        },
        "supplier": "mock",
        "read_only": True,
        "partial": False,
        "omitted_count": 0,
    }


async def test_write_capabilities_and_routes_do_not_exist() -> None:
    forbidden_paths = ("/orders", "/purchase", "/payment", "/topup", "/refund", "/delivery")

    async with make_client() as client:
        capabilities = (await client.get("/api/v1/capabilities")).json()
        statuses = [(await client.post(path)).status_code for path in forbidden_paths]

    assert capabilities["catalog_read"] == {"status": "enabled", "reason": None}
    assert capabilities["catalog_detail"] == {"status": "enabled", "reason": None}
    assert {
        name: capability["status"]
        for name, capability in capabilities.items()
        if name not in {"catalog_read", "catalog_detail"}
    } == {
        "purchase": "disabled",
        "payment": "disabled",
        "top_up": "disabled",
        "refund": "disabled",
        "delivery": "disabled",
    }
    assert statuses == [404] * len(forbidden_paths)
