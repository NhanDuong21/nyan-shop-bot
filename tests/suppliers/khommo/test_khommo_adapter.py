from __future__ import annotations

import json
import socket
from collections.abc import Iterable

import pytest

from nyan_shop_bot.catalog.models import CapabilityStatus
from nyan_shop_bot.suppliers.khommo import (
    PRODUCTION_BASE_URL,
    CreditUnits,
    KhoMmoConfigurationError,
    KhoMmoReadAdapter,
    KhoMmoRequest,
    KhoMmoResponse,
    KhoMmoToken,
    OutcomeCode,
    PaymentMode,
    ReadFailure,
    ReadSuccess,
    VndUnits,
)


def product(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "p-1",
        "sku": "SYN-1",
        "name": "Synthetic product",
        "description": "Offline fixture",
        "priceCredit": 100,
        "priceVnd": 25000,
        "paymentMode": "CREDIT",
        "deliveryType": "synthetic",
        "stock": 4,
        "inStock": True,
    }
    value.update(changes)
    return value


class FakeTransport:
    def __init__(self, outcomes: Iterable[KhoMmoResponse | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.requests: list[KhoMmoRequest] = []

    async def send(self, request: KhoMmoRequest, *, timeout_seconds: float) -> KhoMmoResponse:
        self.requests.append(request)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def adapter(transport: FakeTransport, token: str = "private-token-marker") -> KhoMmoReadAdapter:
    async def no_sleep(_seconds: float) -> None:
        raise AssertionError("adapter must not sleep or retry")

    return KhoMmoReadAdapter(
        token=KhoMmoToken(token), transport=transport, timeout_seconds=2, sleeper=no_sleep
    )


@pytest.mark.asyncio
async def test_account_and_products_preserve_separate_units_and_supplier_prices() -> None:
    account_body = json.dumps(
        {
            "username": "synthetic",
            "firstName": "Test",
            "wallet": {"credit": 123, "vnd": 456000},
        }
    ).encode()
    transport = FakeTransport(
        [KhoMmoResponse(200, account_body), KhoMmoResponse(200, json.dumps([product()]).encode())]
    )
    client = adapter(transport)

    account_outcome = await client.get_account()
    products_outcome = await client.list_products()

    assert isinstance(account_outcome, ReadSuccess)
    assert account_outcome.value.wallet.credit == CreditUnits(123)  # type: ignore[union-attr]
    assert account_outcome.value.wallet.vnd == VndUnits(456000)  # type: ignore[union-attr]
    assert isinstance(products_outcome, ReadSuccess)
    item = products_outcome.value[0]  # type: ignore[index]
    assert item.price_credit == CreditUnits(100)
    assert item.price_vnd == VndUnits(25000)  # no second five-percent discount
    assert item.stock == 4 and item.in_stock is True
    assert item.payment_mode is PaymentMode.CREDIT


@pytest.mark.asyncio
async def test_exact_ordered_query_defaults_search_and_detail_target() -> None:
    transport = FakeTransport(
        [KhoMmoResponse(200, b"[]"), KhoMmoResponse(200, json.dumps(product()).encode())]
    )
    client = adapter(transport)

    await client.list_products(page=2, limit=500, search="name or SKU")
    detail = await client.get_product("id 1")

    assert transport.requests[0].url == (
        PRODUCTION_BASE_URL + "/products?page=2&limit=500&search=name+or+SKU"
    )
    assert transport.requests[1].url == PRODUCTION_BASE_URL + "/products/id%201"
    assert isinstance(detail, ReadSuccess)
    assert all(request.method == "GET" for request in transport.requests)


@pytest.mark.parametrize("product_id", [".", ".."])
@pytest.mark.asyncio
async def test_product_detail_rejects_dot_segments_without_emitting_request(
    product_id: str,
) -> None:
    transport = FakeTransport([])

    with pytest.raises(KhoMmoConfigurationError):
        await adapter(transport).get_product(product_id)

    assert transport.requests == []


@pytest.mark.parametrize("page,limit", [(0, 20), (True, 20), (1, 0), (1, 501), (1, 2.0)])
@pytest.mark.asyncio
async def test_page_and_limit_bounds(page: object, limit: object) -> None:
    transport = FakeTransport([])
    with pytest.raises(KhoMmoConfigurationError):
        await adapter(transport).list_products(page=page, limit=limit)  # type: ignore[arg-type]
    assert transport.requests == []


@pytest.mark.parametrize(
    "status,code",
    [
        (400, OutcomeCode.BAD_REQUEST),
        (401, OutcomeCode.UNAUTHORIZED),
        (404, OutcomeCode.NOT_FOUND),
        (502, OutcomeCode.BAD_GATEWAY),
    ],
)
@pytest.mark.asyncio
async def test_safe_http_errors_are_not_retried(status: int, code: OutcomeCode) -> None:
    transport = FakeTransport([KhoMmoResponse(status, b"private response body")])
    outcome = await adapter(transport).list_products()
    assert outcome == ReadFailure(code, status)
    assert len(transport.requests) == 1
    assert "private response body" not in repr(outcome)


@pytest.mark.asyncio
async def test_timeout_malformed_json_and_unsupported_schema_are_typed_no_retry() -> None:
    cases = [
        (TimeoutError("private"), OutcomeCode.TIMEOUT),
        (KhoMmoResponse(200, b"not-json-private"), OutcomeCode.MALFORMED_JSON),
        (
            KhoMmoResponse(200, json.dumps({"products": []}).encode()),
            OutcomeCode.UNSUPPORTED_SCHEMA,
        ),
        (
            KhoMmoResponse(200, json.dumps([product(extra="undocumented")]).encode()),
            OutcomeCode.UNSUPPORTED_SCHEMA,
        ),
        (
            KhoMmoResponse(200, json.dumps([product(stock=1.5)]).encode()),
            OutcomeCode.UNSUPPORTED_SCHEMA,
        ),
        (
            KhoMmoResponse(200, json.dumps([product(paymentMode="POSTPAID")]).encode()),
            OutcomeCode.UNSUPPORTED_SCHEMA,
        ),
    ]
    for response, code in cases:
        transport = FakeTransport([response])
        assert await adapter(transport).list_products() == ReadFailure(code)
        assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_token_only_in_authorization_and_all_representations_are_redacted() -> None:
    secret = "very-private-bearer-token"
    transport = FakeTransport([KhoMmoResponse(200, b"[]")])
    client = adapter(transport, secret)
    await client.list_products(search="safe")
    request = transport.requests[0]

    assert request.headers["Authorization"] == "Bearer " + secret
    assert secret not in request.url
    assert secret not in repr(request)
    assert secret not in repr(client)
    assert secret not in repr(KhoMmoToken(secret))


def test_only_confirmed_read_capabilities_and_methods_exist() -> None:
    capabilities = KhoMmoReadAdapter.capabilities
    assert capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert capabilities.catalog_detail.status is CapabilityStatus.ENABLED
    assert {
        capabilities.purchase.status,
        capabilities.payment.status,
        capabilities.top_up.status,
        capabilities.refund.status,
        capabilities.delivery.status,
    } == {CapabilityStatus.DISABLED}
    forbidden = {
        "orders",
        "list_orders",
        "order_history",
        "create_order",
        "purchase",
        "payment",
        "top_up",
        "refund",
        "delivery",
        "get_stock",
    }
    assert forbidden.isdisjoint(vars(KhoMmoReadAdapter))


@pytest.mark.asyncio
async def test_injected_transport_never_opens_a_supplier_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("outbound network attempted")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    transport = FakeTransport([KhoMmoResponse(200, b"[]")])
    assert isinstance(await adapter(transport).list_products(), ReadSuccess)
    assert len(transport.requests) == 1
