from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from nyan_shop_bot.bot.callbacks import encode_detail_callback
from nyan_shop_bot.bot.handlers import callback_handler
from nyan_shop_bot.catalog.models import (
    CapabilityStatus,
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogDetailUnsupported,
    CatalogState,
)
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import create_app
from nyan_shop_bot.suppliers.khommo import (
    KhoMmoCatalogReader,
    KhoMmoHttpTransport,
    KhoMmoReadAdapter,
    KhoMmoRequest,
    KhoMmoResponse,
    KhoMmoToken,
    KhoMmoTransportSafetyError,
)


def product(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "p-1",
        "sku": "SKU-1",
        "name": "Documented product",
        "description": "Synthetic response fixture",
        "priceCredit": 100,
        "priceVnd": 25_000,
        "paymentMode": "VND_ONLY",
        "deliveryType": "fixture-only",
        "stock": 4,
        "inStock": True,
    }
    value.update(changes)
    return value


def products_page(
    *items: dict[str, object],
    page: int = 1,
    limit: int = 500,
    total: int | None = None,
    total_pages: int | None = None,
) -> dict[str, object]:
    resolved_total = len(items) if total is None else total
    resolved_pages = (resolved_total + limit - 1) // limit if total_pages is None else total_pages
    return {
        "ok": True,
        "data": list(items),
        "pagination": {
            "page": page,
            "limit": limit,
            "total": resolved_total,
            "totalPages": resolved_pages,
        },
    }


def product_detail(item: dict[str, object] | None = None) -> dict[str, object]:
    return {"ok": True, "data": product() if item is None else item}


class FakeTransport:
    def __init__(self, *responses: KhoMmoResponse) -> None:
        self._responses = iter(responses)
        self.requests: list[KhoMmoRequest] = []

    async def send(self, request: KhoMmoRequest, *, timeout_seconds: float) -> KhoMmoResponse:
        self.requests.append(request)
        return next(self._responses)


def reader(*responses: KhoMmoResponse) -> tuple[KhoMmoCatalogReader, FakeTransport]:
    transport = FakeTransport(*responses)
    adapter = KhoMmoReadAdapter(token=KhoMmoToken("synthetic-secret"), transport=transport)
    fixed_now = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    return KhoMmoCatalogReader(adapter, clock=lambda: fixed_now), transport


@pytest.mark.asyncio
async def test_live_catalog_projects_vnd_product_with_explicit_source_and_pending_mapping() -> None:
    catalog, transport = reader(
        KhoMmoResponse(200, json.dumps(products_page(product())).encode("utf-8"))
    )

    response = await catalog.read_catalog()

    assert response.state is CatalogState.FRESH
    assert response.supplier == "khommo"
    assert response.mode == "khommo-readonly"
    assert response.read_only is True
    assert response.partial is False
    assert response.omitted_count == 0
    assert response.freshness is not None
    assert response.freshness.observed_at == response.freshness.evaluated_at
    assert transport.requests[0].url.endswith("/products?page=1&limit=500")
    assert len(response.items) == 1
    item = response.items[0]
    assert item.supplier == "khommo" and item.mode == "khommo-readonly"
    assert item.price.amount_minor == 25_000 and item.price.currency == "VND"
    assert item.variants[0].mapping.approval.status == "pending"
    public_json = response.model_dump_json()
    assert "fixture-only" not in public_json  # deliveryType stays inside the adapter boundary
    assert "synthetic-secret" not in public_json


@pytest.mark.asyncio
async def test_credit_and_inconsistent_stock_fail_closed_instead_of_guessing_price() -> None:
    for fixture in (
        product(paymentMode="CREDIT"),
        product(stock=4, inStock=False),
    ):
        catalog, _ = reader(KhoMmoResponse(200, json.dumps(products_page(fixture)).encode("utf-8")))
        response = await catalog.read_catalog()
        assert response.state is CatalogState.ERROR
        assert response.error is not None
        assert response.error.code == "unsupported"
        assert response.items == ()


@pytest.mark.asyncio
async def test_owner_approved_partial_catalog_omits_only_missing_description_or_stock() -> None:
    catalog, _ = reader(
        KhoMmoResponse(
            200,
            json.dumps(
                products_page(
                    product(id="kept", sku="KEPT"),
                    product(id="no-description", sku="NO-DESCRIPTION", description=None),
                    product(id="no-stock", sku="NO-STOCK", stock=None),
                )
            ).encode("utf-8"),
        )
    )

    response = await catalog.read_catalog()

    assert response.state is CatalogState.FRESH
    assert response.partial is True
    assert response.omitted_count == 2
    assert [item.id for item in response.items] == ["kept"]
    assert response.items[0].price.currency == "VND"


@pytest.mark.asyncio
async def test_catalog_rejects_more_than_one_bounded_page_without_truncating() -> None:
    fixtures = tuple(product(id=f"p-{index}", sku=f"SKU-{index}") for index in range(500))
    catalog, _ = reader(
        KhoMmoResponse(
            200,
            json.dumps(products_page(*fixtures, total=501, total_pages=2)).encode("utf-8"),
        )
    )

    response = await catalog.read_catalog()

    assert response.state is CatalogState.ERROR
    assert response.error is not None
    assert response.error.code == "unsupported"
    assert response.items == ()


@pytest.mark.asyncio
async def test_catalog_and_detail_failures_are_safe_and_never_enable_writes() -> None:
    catalog, _ = reader(
        KhoMmoResponse(401, b"private body"),
        KhoMmoResponse(404, b"private body"),
    )

    listing = await catalog.read_catalog()
    detail = await catalog.get_product("missing")

    assert listing.state is CatalogState.ERROR
    assert listing.error is not None and listing.error.retryable is False
    assert "private body" not in listing.model_dump_json()
    assert isinstance(detail, CatalogDetailNotFound)
    assert {
        catalog.capabilities.purchase.status,
        catalog.capabilities.payment.status,
        catalog.capabilities.top_up.status,
        catalog.capabilities.refund.status,
        catalog.capabilities.delivery.status,
    } == {CapabilityStatus.DISABLED}


@pytest.mark.asyncio
async def test_product_detail_uses_same_normalized_live_read_projection() -> None:
    catalog, transport = reader(KhoMmoResponse(200, json.dumps(product_detail()).encode("utf-8")))

    detail = await catalog.get_product("p-1")

    assert isinstance(detail, CatalogDetailFound)
    assert detail.item.id == "p-1"
    assert detail.item.read_only is True
    assert transport.requests[0].url.endswith("/products/p-1")


@pytest.mark.asyncio
async def test_product_detail_rejects_a_mismatched_supplier_identity() -> None:
    catalog, _ = reader(
        KhoMmoResponse(
            200,
            json.dumps(product_detail(product(id="different-id"))).encode("utf-8"),
        )
    )

    detail = await catalog.get_product("p-1")

    assert isinstance(detail, CatalogDetailUnsupported)
    assert detail.product_id == "p-1"


@pytest.mark.asyncio
async def test_observed_detail_envelope_reaches_fastapi_and_telegram_consistently() -> None:
    response = KhoMmoResponse(200, json.dumps(product_detail()).encode("utf-8"))
    catalog, transport = reader(response, response)

    class ReadyDatabase:
        async def ping(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    class RecordingMessage:
        def __init__(self) -> None:
            self.answers: list[str] = []

        async def answer(self, text: str, **kwargs: object) -> object:
            del kwargs
            self.answers.append(text)
            return object()

    class RecordingCallback:
        data = encode_detail_callback("p-1")

        def __init__(self, message: RecordingMessage) -> None:
            self.message = message
            self.answered = False

        async def answer(self) -> object:
            self.answered = True
            return object()

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="local",
        app_host="127.0.0.1",
        supplier_mode="khommo-readonly",
        khommo_api_token="synthetic-secret",
        payment_mode="disabled",
        allow_real_purchases=False,
    )
    application = create_app(settings=settings, catalog=catalog, database=ReadyDatabase())
    api_transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 42001))
    async with httpx.AsyncClient(transport=api_transport, base_url="http://test") as client:
        api_response = await client.get("/api/v1/catalog/p-1")

    message = RecordingMessage()
    callback = RecordingCallback(message)
    await callback_handler(callback, catalog)

    assert api_response.status_code == 200
    api_detail = api_response.json()
    assert api_detail["state"] == "found"
    assert api_detail["item"]["id"] == "p-1"
    assert api_detail["item"]["supplier"] == "khommo"
    assert api_detail["item"]["mode"] == "khommo-readonly"
    assert api_detail["item"]["read_only"] is True
    assert callback.answered is True
    assert len(message.answers) == 1
    assert "CHI TIẾT SẢN PHẨM — KHOMMO / CHỈ ĐỌC" in message.answers[0]
    assert f"Tên: {api_detail['item']['name']}" in message.answers[0]
    assert "amount_minor=25000; currency=VND; unit=minor" in message.answers[0]
    assert "available_quantity=4" in message.answers[0]
    assert len(transport.requests) == 2
    assert all(request.url.endswith("/products/p-1") for request in transport.requests)


@pytest.mark.asyncio
async def test_http_transport_sends_only_redacted_get_and_does_not_follow_redirects() -> None:
    secret = "never-print-this-token"
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            302, headers={"Location": "https://api.khommo.vn/api/partner/v1/orders"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = KhoMmoHttpTransport(client=client)
        response = await transport.send(
            KhoMmoRequest(
                method="GET",
                url="https://api.khommo.vn/api/partner/v1/products?page=1&limit=20",
                headers={"Authorization": f"Bearer {secret}"},
            ),
            timeout_seconds=2,
        )

    assert response.status_code == 302
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].headers["Authorization"] == f"Bearer {secret}"
    assert set(seen[0].extensions["timeout"].values()) == {2.0}
    assert secret not in repr(transport)
    assert secret not in repr(response)


@pytest.mark.asyncio
async def test_production_http_client_disables_ambient_proxies_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    closed = False

    class StubClient:
        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    def build_client(**kwargs: object) -> StubClient:
        captured.update(kwargs)
        return StubClient()

    monkeypatch.setattr(httpx, "AsyncClient", build_client)
    transport = KhoMmoHttpTransport()

    assert captured == {"trust_env": False, "follow_redirects": False}
    await transport.aclose()
    assert closed is True


@pytest.mark.parametrize(
    "url",
    [
        "https://api.khommo.vn/api/partner/v1/orders",
        "https://api.khommo.vn/api/partner/v1/products?page=1&limit=20&sort=name",
        "https://example.invalid/api/partner/v1/products?page=1&limit=20",
        "http://api.khommo.vn/api/partner/v1/me",
    ],
)
@pytest.mark.asyncio
async def test_http_transport_rejects_every_unapproved_target_before_network(url: str) -> None:
    called = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = KhoMmoHttpTransport(client=client)
        with pytest.raises(KhoMmoTransportSafetyError):
            await transport.send(
                KhoMmoRequest(
                    method="GET",
                    url=url,
                    headers={"Authorization": "Bearer synthetic-secret"},
                ),
                timeout_seconds=2,
            )

    assert called is False


@pytest.mark.asyncio
async def test_http_transport_bounds_response_without_leaking_body() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"private-response-body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = KhoMmoHttpTransport(client=client, max_response_bytes=4)
        with pytest.raises(KhoMmoTransportSafetyError) as caught:
            await transport.send(
                KhoMmoRequest(
                    method="GET",
                    url="https://api.khommo.vn/api/partner/v1/me",
                    headers={"Authorization": "Bearer synthetic-secret"},
                ),
                timeout_seconds=2,
            )

    assert "private-response-body" not in str(caught.value)
    assert "synthetic-secret" not in str(caught.value)
