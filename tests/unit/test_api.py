"""In-process API contract tests."""

from httpx import ASGITransport, AsyncClient

from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import create_app


class ReadyDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def make_client() -> AsyncClient:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    application = create_app(settings=settings, database=ReadyDatabase())
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
    }


async def test_readiness_uses_database_probe() -> None:
    async with make_client() as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_catalog_is_small_synthetic_and_currency_explicit() -> None:
    async with make_client() as client:
        response = await client.get("/api/v1/catalog")

    body = response.json()
    assert response.status_code == 200
    assert body["mode"] == "mock"
    assert len(body["items"]) == 3
    assert {item["supplier"] for item in body["items"]} == {"mock"}
    assert {item["price"]["currency"] for item in body["items"]} == {"VND"}
    assert all(isinstance(item["price"]["amount_minor"], int) for item in body["items"])


async def test_write_capabilities_and_routes_do_not_exist() -> None:
    forbidden_paths = ("/orders", "/purchase", "/topup", "/refund", "/delivery")

    async with make_client() as client:
        capabilities = (await client.get("/api/v1/capabilities")).json()
        statuses = [(await client.post(path)).status_code for path in forbidden_paths]

    assert capabilities == {
        "catalog_read": True,
        "purchase": False,
        "top_up": False,
        "refund": False,
        "delivery_credentials": False,
    }
    assert statuses == [404] * len(forbidden_paths)
