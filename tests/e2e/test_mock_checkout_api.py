"""HTTP checkout contract with no external transport or real supplier calls."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import create_app
from nyan_shop_bot.orders.fakes import InMemoryOrderRepository

TOKEN = "synthetic-local-demo-key-0000000000000001"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Origin": "http://127.0.0.1:5173"}


class ReadyDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def client(
    *,
    repository: InMemoryOrderRepository | None = None,
    settings: Settings | None = None,
    remote: bool = False,
) -> AsyncClient:
    application = create_app(
        settings=settings or Settings(_env_file=None, mock_checkout_access_token=TOKEN),  # type: ignore[call-arg]
        catalog=FakeCatalogReader(),
        database=ReadyDatabase(),
        order_repository=repository or InMemoryOrderRepository(),
    )
    return AsyncClient(
        transport=ASGITransport(
            app=application, client=("203.0.113.9", 12345) if remote else ("127.0.0.1", 12345)
        ),
        base_url="http://localhost",
    )


def body(key: str, scenario: str = "success") -> dict[str, object]:
    return {
        "product_id": "learning-pass",
        "variant_id": "learning-pass-30d",
        "quantity": 1,
        "idempotency_key": key,
        "max_unit_price": {"amount_minor": 49000, "currency": "VND", "unit": "minor"},
        "scenario": scenario,
    }


@pytest.mark.parametrize(
    ("headers", "remote", "expected"),
    (
        ({}, False, 401),
        ({"Authorization": "Bearer wrong"}, False, 401),
        (HEADERS, True, 403),
        ({"Authorization": f"Bearer {TOKEN}", "Origin": "https://evil.example"}, False, 403),
    ),
)
async def test_access_control(headers: dict[str, str], remote: bool, expected: int) -> None:
    async with client(remote=remote) as api:
        response = await api.get("/api/v1/mock-checkout/orders", headers=headers)
    assert response.status_code == expected


async def test_live_read_configuration_cannot_checkout() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supplier_mode="khommo-readonly",
        khommo_api_token="synthetic-read-token",
        mock_checkout_access_token=TOKEN,
    )
    async with client(settings=settings) as api:
        response = await api.post(
            "/api/v1/mock-checkout/orders", json=body("disabled-01"), headers=HEADERS
        )
    assert response.status_code == 403


async def test_currency_stock_identity_and_extra_fields_are_rejected() -> None:
    async with client() as api:
        for changes, expected in (
            ({"max_unit_price": {"amount_minor": 49000, "currency": "USD", "unit": "minor"}}, 409),
            ({"max_unit_price": {"amount_minor": 100, "currency": "VND", "unit": "minor"}}, 409),
            ({"product_id": "not-a-product"}, 409),
            ({"quantity": 100}, 409),
            ({"supplier_code": "khommo"}, 422),
        ):
            response = await api.post(
                "/api/v1/mock-checkout/orders",
                json={**body("safety-01"), **changes},
                headers=HEADERS,
            )
            assert response.status_code == expected
        history = await api.get("/api/v1/mock-checkout/orders", headers=HEADERS)
    assert history.json() == []


async def test_success_failure_unknown_reconciliation_and_duplicate_submit() -> None:
    repository = InMemoryOrderRepository()
    async with client(repository=repository) as api:
        catalog = await api.get("/api/v1/mock-checkout/catalog", headers=HEADERS)
        assert catalog.status_code == 200
        assert catalog.json()["items"][0]["variants"][0]["price"] == {
            "amount_minor": 49000,
            "currency": "VND",
            "unit": "minor",
        }
        success, duplicate = await asyncio.gather(
            api.post("/api/v1/mock-checkout/orders", json=body("same-key-01"), headers=HEADERS),
            api.post("/api/v1/mock-checkout/orders", json=body("same-key-01"), headers=HEADERS),
        )
        assert success.status_code == duplicate.status_code == 200
        assert success.json() == duplicate.json()
        assert success.json()["purchase_state"] == "SUCCEEDED"
        assert success.json()["total_price"] == {
            "amount_minor": 49000,
            "currency": "VND",
            "unit": "minor",
        }

        failed = await api.post(
            "/api/v1/mock-checkout/orders", json=body("fail-key-01", "failed_safe"), headers=HEADERS
        )
        unknown = await api.post(
            "/api/v1/mock-checkout/orders", json=body("unknown-01", "unknown"), headers=HEADERS
        )
        assert failed.json()["purchase_state"] == "FAILED_SAFE"
        assert failed.json()["failure_code"] == "OUT_OF_STOCK"
        assert unknown.json()["purchase_state"] == "UNKNOWN"

        intent_id = unknown.json()["intent_id"]
        unresolved = await api.post(
            f"/api/v1/mock-checkout/orders/{intent_id}/reconcile",
            json={"evidence": "unresolved"},
            headers=HEADERS,
        )
        assert unresolved.json()["purchase_state"] == "RECONCILING"
        resolved = await api.post(
            f"/api/v1/mock-checkout/orders/{intent_id}/reconcile",
            json={"evidence": "confirmed_success"},
            headers=HEADERS,
        )
        assert resolved.json()["purchase_state"] == "SUCCEEDED"
        again = await api.post(
            f"/api/v1/mock-checkout/orders/{intent_id}/reconcile",
            json={"evidence": "confirmed_out_of_stock"},
            headers=HEADERS,
        )
        assert again.json() == resolved.json()
        history = await api.get("/api/v1/mock-checkout/orders", headers=HEADERS)
        assert len(history.json()) == 3
        assert all("supplier" not in item for item in history.json())
