"""In-process API contract tests."""

from httpx import ASGITransport, AsyncClient

from nyan_shop_bot.catalog.mock import FakeCatalogReader, FakeCatalogScenario
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import build_catalog_reader, create_app
from nyan_shop_bot.suppliers.khommo import KhoMmoCatalogReader


class ReadyDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


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
            await client.get("/api/v1/catalog"),
            await client.get("/api/v1/catalog/p-1"),
            await client.get("/api/v1/capabilities"),
        ]
    async with AsyncClient(transport=loopback_transport, base_url="http://test") as client:
        capabilities = await client.get("/api/v1/capabilities")

    assert health.status_code == 200
    assert [response.status_code for response in blocked] == [403, 403, 403]
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
