"""Local-only HTTP contract for catalog curation."""

from httpx import ASGITransport, AsyncClient

from nyan_shop_bot.catalog.curation.repository import InMemoryCatalogCurationRepository
from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.catalog.models import (
    CatalogDetailResponse,
    CatalogResponse,
    CatalogState,
    CatalogSupplier,
)
from nyan_shop_bot.catalog.registry import CatalogRegistry
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import create_app


class ReadyDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class LiveReader:
    capabilities = FakeCatalogReader.capabilities

    def __init__(self, supplier: CatalogSupplier) -> None:
        self._supplier = supplier
        self._delegate = FakeCatalogReader()

    async def read_catalog(self) -> CatalogResponse:
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


def application(*, app_env: str = "local"):
    supplier_mode = "multi-readonly" if app_env == "local" else "mock"
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env=app_env,
        supplier_mode=supplier_mode,
        khommo_api_token="synthetic-khommo" if supplier_mode == "multi-readonly" else None,
        vietshare_api_id=("synthetic-vietshare-id" if supplier_mode == "multi-readonly" else None),
        vietshare_api_secret=(
            "synthetic-vietshare-secret" if supplier_mode == "multi-readonly" else None
        ),
    )
    registry = CatalogRegistry(
        {
            "khommo": LiveReader("khommo"),
            "vietshare": LiveReader("vietshare"),
        }
    )
    return create_app(
        settings=settings,
        catalogs=registry,
        database=ReadyDatabase(),
        curation_repository=InMemoryCatalogCurationRepository(),
    )


async def test_workspace_is_loopback_only_and_redacted() -> None:
    app = application()
    local_transport = ASGITransport(app=app, client=("127.0.0.1", 41000))
    remote_transport = ASGITransport(app=app, client=("203.0.113.8", 41001))

    async with AsyncClient(transport=local_transport, base_url="http://test") as client:
        local = await client.get("/api/v1/admin/catalog-curation")
    async with AsyncClient(transport=remote_transport, base_url="http://test") as client:
        remote = await client.get("/api/v1/admin/catalog-curation")

    assert local.status_code == 200
    body = local.json()
    assert body["read_only"] is True
    assert body["supplier_writes_enabled"] is False
    assert len(body["offers"]) == 2
    assert "credential" not in local.text.lower()
    assert "delivery" not in local.text.lower()
    assert remote.status_code == 403


async def test_write_requires_local_origin_json_and_optimistic_revision() -> None:
    app = application()
    transport = ASGITransport(app=app, client=("127.0.0.1", 41000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        workspace = (await client.get("/api/v1/admin/catalog-curation")).json()
        key = workspace["offers"][0]["key"]
        payload = {
            "expected_revision": 0,
            "listings": [
                {
                    "id": "nyan-learning",
                    "name": "Gói học tập Nyan",
                    "description": "Mô tả dòng một.\nMô tả dòng hai.",
                    "category": "Học tập",
                    "visible": True,
                    "sort_order": 0,
                    "retail_price": {
                        "amount_minor": 125000,
                        "currency": "VND",
                        "unit": "minor",
                    },
                    "offer_keys": [key],
                }
            ],
        }
        no_origin = await client.put("/api/v1/admin/catalog-curation", json=payload)
        wrong_type = await client.put(
            "/api/v1/admin/catalog-curation",
            content="{}",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Content-Type": "text/plain",
            },
        )
        saved = await client.put(
            "/api/v1/admin/catalog-curation",
            json=payload,
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        stale = await client.put(
            "/api/v1/admin/catalog-curation",
            json=payload,
            headers={"Origin": "http://127.0.0.1:5173"},
        )

    assert no_origin.status_code == 403
    assert wrong_type.status_code == 403
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["listings"][0]["description"] == "Mô tả dòng một.\nMô tả dòng hai."
    assert stale.status_code == 409
    assert "reload" in stale.json()["detail"]


async def test_nonlocal_environment_rejects_admin_route() -> None:
    app = application(app_env="test")
    transport = ASGITransport(app=app, client=("127.0.0.1", 41000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/catalog-curation")

    assert response.status_code == 403


async def test_storefront_is_loopback_only_redacted_and_matches_detail() -> None:
    app = application()
    local_transport = ASGITransport(app=app, client=("127.0.0.1", 41000))
    remote_transport = ASGITransport(app=app, client=("203.0.113.8", 41001))
    async with AsyncClient(transport=local_transport, base_url="http://test") as client:
        workspace = (await client.get("/api/v1/admin/catalog-curation")).json()
        offer = workspace["offers"][0]
        saved = await client.put(
            "/api/v1/admin/catalog-curation",
            json={
                "expected_revision": 0,
                "listings": [
                    {
                        "id": "nyan-learning",
                        "name": "Gói KhoMMO và VietShare",
                        "description": "Mô tả dòng một.\nMô tả dòng hai.",
                        "category": "Học tập",
                        "visible": True,
                        "sort_order": 0,
                        "retail_price": {
                            "amount_minor": 125000,
                            "currency": "VND",
                            "unit": "minor",
                        },
                        "offer_keys": [offer["key"]],
                    }
                ],
            },
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        catalog = await client.get("/api/v1/storefront/catalog")
        detail = await client.get("/api/v1/storefront/catalog/nyan-learning")
    async with AsyncClient(transport=remote_transport, base_url="http://test") as client:
        remote = await client.get("/api/v1/storefront/catalog")

    assert saved.status_code == 200
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["revision"] == 1
    assert body["state"] == "ready"
    assert body["supplier_provenance_exposed"] is False
    assert body["purchase_enabled"] is False
    assert body["payment_enabled"] is False
    assert body["items"] == [
        {
            "id": "nyan-learning",
            "name": "Gói Nyan và Nyan",
            "description": "Mô tả dòng một.\nMô tả dòng hai.",
            "category": "Học tập",
            "price": {"amount_minor": 125000, "currency": "VND", "unit": "minor"},
            "availability": "in_stock",
            "read_only": True,
        }
    ]
    rendered = catalog.text.lower()
    for forbidden in (
        "khommo",
        "vietshare",
        offer["supplier_product_id"].lower(),
        "available_quantity",
        "delivery",
        "credential",
    ):
        assert forbidden not in rendered
    assert detail.status_code == 200
    assert detail.json() == {"state": "found", "item": body["items"][0]}
    assert remote.status_code == 403


async def test_supplier_and_money_routes_remain_absent() -> None:
    app = application()
    transport = ASGITransport(app=app, client=("127.0.0.1", 41000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = [
            (await client.post(path)).status_code
            for path in ("/orders", "/purchase", "/payment", "/topup", "/refund", "/delivery")
        ]

    assert statuses == [404] * 6
