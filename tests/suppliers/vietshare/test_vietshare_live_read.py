"""Synthetic end-to-end coverage for the VietShare live-read product path."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from itertools import count

import httpx
import pytest

from nyan_shop_bot.bot.callbacks import encode_detail_callback
from nyan_shop_bot.bot.handlers import callback_handler, catalog_handler
from nyan_shop_bot.catalog.models import (
    CapabilityStatus,
    CatalogDetailFound,
    CatalogState,
)
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import create_app
from nyan_shop_bot.suppliers.vietshare import (
    PRODUCTION_BASE_URL,
    VietShareCatalogReader,
    VietShareCredentials,
    VietShareHttpTransport,
    VietShareReadAdapter,
    VietShareRequest,
    VietShareResponse,
    VietShareTransportSafetyError,
    build_signed_read_request,
)


def product_fixture(
    *,
    product_id: int = 17,
    description: str = "Offline-only VietShare fixture.",
) -> dict[str, object]:
    return {
        "id": product_id,
        "name": "Synthetic VietShare item",
        "description": description,
        "price": 32_000,
        "flash_sale_id": None,
        "stock": 9,
        "allow_quantity": True,
        "max_quantity": 3,
        "currency": ["VND", "USD"],
        "price_usd": "1.25",
    }


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class RoutingTransport:
    def __init__(self, *, description: str = "Offline-only VietShare fixture.") -> None:
        self.requests: list[VietShareRequest] = []
        self.description = description

    async def send(self, request: VietShareRequest, *, timeout_seconds: float) -> VietShareResponse:
        assert timeout_seconds == 3.0
        self.requests.append(request)
        if request.path_with_query == "/v1/products":
            body = encoded(
                {"count": 1, "products": [product_fixture(description=self.description)]}
            )
            return VietShareResponse(status_code=200, body=body)
        if request.path_with_query == "/v1/products/17":
            return VietShareResponse(
                status_code=200,
                body=encoded(product_fixture(description=self.description)),
            )
        return VietShareResponse(status_code=404, body=b"{}")


async def no_sleep(_seconds: float) -> None:
    raise AssertionError("successful synthetic reads must not sleep")


def make_reader(
    *, description: str = "Offline-only VietShare fixture."
) -> tuple[VietShareCatalogReader, RoutingTransport]:
    nonces = count(1)
    transport = RoutingTransport(description=description)
    adapter = VietShareReadAdapter(
        credentials=VietShareCredentials(
            api_id="synthetic-vietshare-id",
            api_secret="synthetic-vietshare-secret",
        ),
        transport=transport,
        clock=lambda: 1_760_000_000,
        nonce_source=lambda: f"synthetic-nonce-{next(nonces):08d}",
        retry_sleeper=no_sleep,
        timeout_seconds=3.0,
        max_retries=0,
    )
    fixed_now = datetime(2026, 9, 22, tzinfo=UTC)
    return VietShareCatalogReader(adapter, clock=lambda: fixed_now), transport


class ReadyDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, Mapping[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> object:
        self.answers.append((text, kwargs))
        return object()


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answers = 0

    async def answer(self) -> object:
        self.answers += 1
        return object()


async def test_catalog_and_detail_share_one_normalized_vnd_projection() -> None:
    reader, transport = make_reader()

    catalog = await reader.read_catalog()
    detail = await reader.get_product("17")

    assert catalog.state is CatalogState.FRESH
    assert catalog.supplier == "vietshare"
    assert catalog.mode == "vietshare-readonly"
    assert catalog.read_only is True
    assert catalog.partial is False and catalog.omitted_count == 0
    assert isinstance(detail, CatalogDetailFound)
    assert detail.item == catalog.items[0]
    assert detail.item.price.amount_minor == 32_000
    assert detail.item.price.currency == "VND"
    assert detail.item.price.unit == "minor"
    assert detail.item.available_quantity == 9
    assert reader.capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert reader.capabilities.catalog_detail.status is CapabilityStatus.ENABLED
    assert {
        reader.capabilities.purchase.status,
        reader.capabilities.payment.status,
        reader.capabilities.top_up.status,
        reader.capabilities.refund.status,
        reader.capabilities.delivery.status,
    } == {CapabilityStatus.DISABLED}
    assert [request.path_with_query for request in transport.requests] == [
        "/v1/products",
        "/v1/products/17",
    ]
    assert all(request.method == "GET" and request.body == b"" for request in transport.requests)


async def test_catalog_and_detail_strip_telegram_premium_custom_emoji() -> None:
    reader, _ = make_reader(
        description=(
            '<tg-emoji emoji-id="5310278924616356636">🎯</tg-emoji>'
            "Không giới hạn thời gian "
            '<tg-emoji emoji-id="5451882707875276247">🕯</tg-emoji>'
            "Sử dụng full model"
        )
    )

    catalog = await reader.read_catalog()
    detail = await reader.get_product("17")

    assert catalog.items[0].description == "Không giới hạn thời gian Sử dụng full model"
    assert isinstance(detail, CatalogDetailFound)
    assert detail.item.description == catalog.items[0].description
    assert "tg-emoji" not in detail.item.description
    assert "🎯" not in detail.item.description
    assert "🕯" not in detail.item.description


async def test_invalid_detail_identifier_never_reaches_transport() -> None:
    reader, transport = make_reader()

    responses = [
        await reader.get_product("017"),
        await reader.get_product("-1"),
        await reader.get_product("not-an-id"),
    ]

    assert all(response.state == "not_found" for response in responses)
    assert transport.requests == []


async def test_fastapi_admin_contract_and_telegram_use_the_same_reader() -> None:
    reader, _ = make_reader()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="local",
        app_host="127.0.0.1",
        supplier_mode="vietshare-readonly",
        vietshare_api_id="synthetic-vietshare-id",
        vietshare_api_secret="synthetic-vietshare-secret",
        payment_mode="disabled",
        allow_real_purchases=False,
    )
    application = create_app(settings=settings, catalog=reader, database=ReadyDatabase())
    api_transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 42001))
    async with httpx.AsyncClient(transport=api_transport, base_url="http://test") as client:
        api_catalog = (await client.get("/api/v1/catalog")).json()
        api_detail = (await client.get("/api/v1/catalog/17")).json()

    catalog_message = FakeMessage()
    await catalog_handler(catalog_message, reader)
    detail_message = FakeMessage()
    callback = FakeCallback(encode_detail_callback("17"), detail_message)
    await callback_handler(callback, reader)

    assert api_catalog["supplier"] == "vietshare"
    assert api_catalog["mode"] == "vietshare-readonly"
    assert api_detail["state"] == "found"
    assert api_detail["item"] == api_catalog["items"][0]
    assert "DANH MỤC — VIETSHARE / CHỈ ĐỌC" in catalog_message.answers[0][0]
    assert "Synthetic VietShare item" in catalog_message.answers[0][0]
    assert "CHI TIẾT SẢN PHẨM — VIETSHARE / CHỈ ĐỌC" in detail_message.answers[0][0]
    assert "amount_minor=32000; currency=VND; unit=minor" in detail_message.answers[0][0]
    assert callback.answers == 1


def signed_request(endpoint: str = "/products") -> VietShareRequest:
    return build_signed_read_request(
        credentials=VietShareCredentials(
            api_id="synthetic-id",
            api_secret="synthetic-secret",
        ),
        base_url=PRODUCTION_BASE_URL,
        endpoint=endpoint,
        timestamp=1_760_000_000,
        nonce="synthetic-nonce-0001",
        raw_body=b"",
    )


async def test_http_transport_sends_get_without_redirects_or_ambient_target_changes() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://example.invalid/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = VietShareHttpTransport(client=client)
        response = await transport.send(signed_request(), timeout_seconds=2.0)

    assert response.status_code == 302
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].url == "https://token.vietshare.site/v1/products"
    assert seen[0].content == b""
    assert "Location" not in response.headers


@pytest.mark.parametrize("endpoint", ["/catalog", "/stock/17"])
async def test_http_transport_rejects_read_aliases_outside_the_owner_grant(endpoint: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("rejected route reached network transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = VietShareHttpTransport(client=client)
        with pytest.raises(VietShareTransportSafetyError):
            await transport.send(signed_request(endpoint), timeout_seconds=2.0)


async def test_http_transport_rejects_every_write_or_unapproved_host_before_io() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = VietShareHttpTransport(client=client)
        base = signed_request()
        write = VietShareRequest(
            method="POST",
            url="https://token.vietshare.site/v1/orders",
            path_with_query="/v1/orders",
            headers=base.headers,
            body=b"{}",
        )
        wrong_host = VietShareRequest(
            method="GET",
            url="https://example.invalid/v1/products",
            path_with_query="/v1/products",
            headers=base.headers,
            body=b"",
        )
        for request in (write, wrong_host):
            with pytest.raises(VietShareTransportSafetyError):
                await transport.send(request, timeout_seconds=2.0)

    assert calls == 0
