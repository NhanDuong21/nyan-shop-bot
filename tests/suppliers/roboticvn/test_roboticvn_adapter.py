"""Request, failure, capability, and network-boundary tests for Roboticvn v2."""

from __future__ import annotations

import inspect
import json
import logging
import socket
from collections.abc import Iterable

import pytest

from nyan_shop_bot.catalog.models import CapabilityStatus
from nyan_shop_bot.suppliers.roboticvn import (
    GLOBAL_AUTH_HEADER,
    PRODUCTION_ORIGIN,
    Locale,
    OutcomeCode,
    ReadFailure,
    ReadSuccess,
    RoboticvnApiKey,
    RoboticvnConfigurationError,
    RoboticvnReadAdapter,
    RoboticvnRequest,
    RoboticvnResponse,
    UnsupportedMonetaryProjection,
    WalletCurrencyCode,
)


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def products_body() -> bytes:
    return encoded(
        {
            "data": [{"id": "product-synthetic-1", "title": "Synthetic product"}],
            "meta": {"count": 1, "limit": 20, "offset": 0},
        }
    )


def product_body() -> bytes:
    return encoded({"data": {"id": "product-synthetic-1", "title": "Synthetic product"}})


def balance_body() -> bytes:
    return encoded({"data": {"vnd": 0}})


def transactions_body() -> bytes:
    return encoded(
        {
            "data": [{}],
            "meta": {"count": 1, "limit": 20, "offset": 0},
        }
    )


class FakeTransport:
    """A deterministic fake with no code path capable of opening a socket."""

    def __init__(self, outcomes: Iterable[RoboticvnResponse | Exception | object]) -> None:
        self._outcomes = iter(outcomes)
        self.requests: list[RoboticvnRequest] = []
        self.timeouts: list[float] = []

    async def send(self, request: RoboticvnRequest, *, timeout_seconds: float) -> RoboticvnResponse:
        self.requests.append(request)
        self.timeouts.append(timeout_seconds)
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]


def adapter(
    transport: FakeTransport,
    *,
    key: str = "synthetic-api-key-marker",
    timeout_seconds: float = 2,
) -> RoboticvnReadAdapter:
    return RoboticvnReadAdapter(
        api_key=RoboticvnApiKey(key),
        transport=transport,
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.asyncio
async def test_all_four_authorized_get_paths_and_default_queries_are_exact() -> None:
    transport = FakeTransport(
        [
            RoboticvnResponse(200, products_body()),
            RoboticvnResponse(200, product_body()),
            RoboticvnResponse(200, balance_body()),
            RoboticvnResponse(200, transactions_body()),
        ]
    )
    client = adapter(transport)

    outcomes = (
        await client.list_products(),
        await client.get_product("product-synthetic-1"),
        await client.get_wallet_balance(),
        await client.list_wallet_transactions(),
    )

    assert all(isinstance(outcome, ReadSuccess) for outcome in outcomes)
    assert [request.url for request in transport.requests] == [
        PRODUCTION_ORIGIN + "/api/v2/products?limit=20&offset=0",
        PRODUCTION_ORIGIN + "/api/v2/products/product-synthetic-1",
        PRODUCTION_ORIGIN + "/api/v2/wallet/balance",
        (PRODUCTION_ORIGIN + "/api/v2/wallet/transactions?currency_code=vnd&limit=20&offset=0"),
    ]
    assert all(request.method == "GET" for request in transport.requests)
    assert transport.timeouts == [2.0, 2.0, 2.0, 2.0]


@pytest.mark.asyncio
async def test_product_query_parameters_have_one_deterministic_encoded_order() -> None:
    transport = FakeTransport([RoboticvnResponse(200, products_body())])

    await adapter(transport).list_products(
        limit=100,
        offset=7,
        search="name / synthetic",
        category_id="category&one",
        locale=Locale.ENGLISH,
    )

    assert transport.requests[0].url == (
        PRODUCTION_ORIGIN
        + "/api/v2/products?limit=100&offset=7&search=name+%2F+synthetic"
        + "&category_id=category%26one&locale=en-US"
    )


@pytest.mark.asyncio
async def test_detail_and_balance_locale_queries_are_exact() -> None:
    transport = FakeTransport(
        [RoboticvnResponse(200, product_body()), RoboticvnResponse(200, balance_body())]
    )
    client = adapter(transport)

    await client.get_product("id with % literal", locale="vi-VN")
    balance = await client.get_wallet_balance(locale=Locale.ENGLISH)

    assert transport.requests[0].url == (
        PRODUCTION_ORIGIN + "/api/v2/products/id%20with%20%25%20literal?locale=vi-VN"
    )
    assert transport.requests[1].url == (PRODUCTION_ORIGIN + "/api/v2/wallet/balance?locale=en-US")
    assert isinstance(balance, ReadSuccess)
    assert isinstance(balance.value.monetary_projection, UnsupportedMonetaryProjection)  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_wallet_transaction_query_parameters_have_one_deterministic_order() -> None:
    transport = FakeTransport([RoboticvnResponse(200, transactions_body())])

    await adapter(transport).list_wallet_transactions(
        currency_code=WalletCurrencyCode.USD,
        limit=1,
        offset=99,
        locale="vi-VN",
    )

    assert transport.requests[0].url == (
        PRODUCTION_ORIGIN
        + "/api/v2/wallet/transactions?currency_code=usd&limit=1&offset=99&locale=vi-VN"
    )


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("list_products", {"limit": 0}),
        ("list_products", {"limit": 101}),
        ("list_products", {"limit": True}),
        ("list_products", {"limit": 20.0}),
        ("list_products", {"offset": -1}),
        ("list_products", {"offset": False}),
        ("list_products", {"search": 1}),
        ("list_products", {"category_id": []}),
        ("list_products", {"locale": "en-us"}),
        ("get_product", {"product_id": "safe", "locale": "fr-FR"}),
        ("get_wallet_balance", {"locale": True}),
        ("list_wallet_transactions", {"currency_code": "VND"}),
        ("list_wallet_transactions", {"currency_code": "eur"}),
        ("list_wallet_transactions", {"limit": 0}),
        ("list_wallet_transactions", {"offset": -1}),
        ("list_wallet_transactions", {"locale": "vi-vn"}),
    ],
)
@pytest.mark.asyncio
async def test_query_bounds_and_enums_fail_before_transport(
    method: str,
    kwargs: dict[str, object],
) -> None:
    transport = FakeTransport([])
    operation = getattr(adapter(transport), method)

    with pytest.raises(RoboticvnConfigurationError):
        await operation(**kwargs)

    assert transport.requests == []


@pytest.mark.parametrize(
    "product_id",
    [
        "",
        ".",
        "..",
        "/",
        "\\",
        "safe/unsafe",
        "safe\\unsafe",
        "line\nbreak",
        "null\0byte",
        "%2f",
        "%2F",
        "%5c",
        "%252f",
        "%25252F",
        "%00",
        "%2500",
        "%2e",
        "%2e%2e",
        ".%2e",
        "%252e%252e",
        "%c0%af",
        "%ef%bc%8f",
        "\uff052e",
        "\uff052e\uff052e",
        "\uff05252e",
        "%ef%bc%852e",
        "%25ef%25bc%25852e",
        "safe\uff052funsafe",
        "safe\uff055cunsafe",
        "\uff052500",
        "\uff0f",
        "\uff3c",
        "\uff0e\uff0e",
        "\u2024\u2024",
        "zero\u200bwidth",
    ],
)
@pytest.mark.asyncio
async def test_hostile_or_normalization_escaping_product_ids_never_reach_transport(
    product_id: str,
) -> None:
    transport = FakeTransport([])

    with pytest.raises(RoboticvnConfigurationError):
        await adapter(transport).get_product(product_id)

    assert transport.requests == []


@pytest.mark.parametrize("value", ["sku.1", "50%off", "space id", "\u0111i\u1ec7n-t\u1eed"])
@pytest.mark.asyncio
async def test_safe_single_segment_product_ids_are_percent_encoded_once(value: str) -> None:
    transport = FakeTransport([RoboticvnResponse(200, product_body())])
    outcome = await adapter(transport).get_product(value)

    assert isinstance(outcome, ReadSuccess)
    assert transport.requests[0].url.startswith(PRODUCTION_ORIGIN + "/api/v2/products/")
    assert "/api/v2/products//" not in transport.requests[0].url


@pytest.mark.parametrize(
    "status,code",
    [
        (400, OutcomeCode.BAD_REQUEST),
        (401, OutcomeCode.UNAUTHORIZED),
        (404, OutcomeCode.NOT_FOUND),
        (429, OutcomeCode.RATE_LIMITED),
        (500, OutcomeCode.SUPPLIER_ERROR),
    ],
)
@pytest.mark.asyncio
async def test_documented_http_errors_are_typed_redacted_and_never_retried(
    status: int,
    code: OutcomeCode,
) -> None:
    body = b"supplier-private-response-marker"
    transport = FakeTransport([RoboticvnResponse(status, body, headers={"Retry-After": "private"})])

    outcome = await adapter(transport).list_products()

    assert outcome == ReadFailure(code, status)
    assert outcome.attempts == 1
    assert outcome.retryable is False
    assert len(transport.requests) == 1
    assert body.decode() not in repr(outcome)


@pytest.mark.parametrize(
    "outcome,code",
    [
        (TimeoutError("supplier-private-timeout-marker"), OutcomeCode.TIMEOUT),
        (RuntimeError("supplier-private-transport-marker"), OutcomeCode.TRANSPORT_ERROR),
        (object(), OutcomeCode.TRANSPORT_ERROR),
        (RoboticvnResponse(200, b"not-json-private-marker"), OutcomeCode.MALFORMED_JSON),
        (
            RoboticvnResponse(200, encoded({"data": [], "meta": {"count": True}})),
            OutcomeCode.UNSUPPORTED_SCHEMA,
        ),
        (RoboticvnResponse(418, b"private"), OutcomeCode.UNEXPECTED_STATUS),
    ],
)
@pytest.mark.asyncio
async def test_timeout_transport_malformed_and_schema_failures_are_typed_without_retry(
    outcome: RoboticvnResponse | Exception | object,
    code: OutcomeCode,
) -> None:
    transport = FakeTransport([outcome])

    result = await adapter(transport).list_products()

    assert isinstance(result, ReadFailure)
    assert result.code is code
    assert result.attempts == 1
    assert result.retryable is False
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_api_key_exists_only_in_redacted_header_mapping(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "api-key-private-marker"
    transport = FakeTransport([RoboticvnResponse(200, products_body())])
    client = adapter(transport, key=secret)

    with caplog.at_level(logging.DEBUG):
        await client.list_products(search="safe")

    request = transport.requests[0]
    assert dict(request.headers) == {GLOBAL_AUTH_HEADER: secret}
    assert secret not in request.url
    combined = " ".join(
        (
            repr(RoboticvnApiKey(secret)),
            str(RoboticvnApiKey(secret)),
            repr(request),
            repr(request.headers),
            str(request.headers),
            repr(client),
            caplog.text,
        )
    )
    assert secret not in combined
    assert "<redacted>" in combined


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("list_products", {"search": "api key+private-marker"}),
        ("list_products", {"category_id": "api key+private-marker"}),
        ("get_product", {"product_id": "api key+private-marker"}),
    ],
)
@pytest.mark.asyncio
async def test_api_key_repeated_in_query_or_path_never_reaches_transport(
    method: str,
    kwargs: dict[str, object],
) -> None:
    secret = "api key+private-marker"
    transport = FakeTransport([])
    operation = getattr(adapter(transport, key=secret), method)

    with pytest.raises(RoboticvnConfigurationError) as caught:
        await operation(**kwargs)

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert transport.requests == []


@pytest.mark.asyncio
async def test_api_key_guard_uses_single_decode_component_semantics() -> None:
    secret = "alpha beta"
    transport = FakeTransport(
        [
            RoboticvnResponse(200, product_body()),
            RoboticvnResponse(200, product_body()),
            RoboticvnResponse(200, products_body()),
        ]
    )
    client = adapter(transport, key=secret)

    outcomes = (
        await client.get_product("alpha+beta"),
        await client.get_product("alpha%20beta"),
        await client.list_products(search="alpha%20beta"),
    )

    assert all(isinstance(outcome, ReadSuccess) for outcome in outcomes)
    assert [request.url for request in transport.requests] == [
        PRODUCTION_ORIGIN + "/api/v2/products/alpha%2Bbeta",
        PRODUCTION_ORIGIN + "/api/v2/products/alpha%2520beta",
        PRODUCTION_ORIGIN + "/api/v2/products?limit=20&offset=0&search=alpha%2520beta",
    ]


def test_raw_request_preserves_literal_plus_path_semantics() -> None:
    request = RoboticvnRequest(
        method="GET",
        url=PRODUCTION_ORIGIN + "/api/v2/products/alpha+beta",
        headers={GLOBAL_AUTH_HEADER: "alpha beta"},
    )

    assert request.url.endswith("/alpha+beta")


def test_raw_response_representation_hides_body_and_headers() -> None:
    private = "supplier-private-response-marker"
    response = RoboticvnResponse(
        200,
        private.encode(),
        headers={"X-Private": private},
    )
    combined = repr(response) + repr(response.headers)
    assert private not in combined
    assert "<redacted>" in combined


@pytest.mark.parametrize(
    "status,body",
    [(True, b"{}"), ("200", b"{}"), (200, "{}")],
)
def test_raw_response_requires_integer_status_and_exact_bytes(
    status: object,
    body: object,
) -> None:
    with pytest.raises(RoboticvnConfigurationError):
        RoboticvnResponse(status, body)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_transport_exception_text_cannot_escape_into_outcome_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "api-key-exception-private-marker"
    body = "supplier-body-exception-private-marker"
    transport = FakeTransport([RuntimeError(f"{secret} {body}")])

    with caplog.at_level(logging.DEBUG):
        outcome = await adapter(transport, key=secret).get_wallet_balance()

    assert outcome == ReadFailure(OutcomeCode.TRANSPORT_ERROR)
    combined = repr(outcome) + caplog.text
    assert secret not in combined
    assert body not in combined


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan"), "10"])
def test_timeout_must_be_positive_finite_and_never_constructs_transport_call(
    timeout: object,
) -> None:
    with pytest.raises(RoboticvnConfigurationError):
        adapter(FakeTransport([]), timeout_seconds=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("key", ["", "line\nbreak", "carriage\rreturn", "null\0byte"])
def test_api_key_validation_never_echoes_rejected_input(key: str) -> None:
    with pytest.raises(RoboticvnConfigurationError) as caught:
        RoboticvnApiKey(key)
    if key:
        assert key not in str(caught.value)
        assert key not in repr(caught.value)


def test_only_supported_catalog_capabilities_are_enabled() -> None:
    capabilities = RoboticvnReadAdapter.capabilities
    assert capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert capabilities.catalog_detail.status is CapabilityStatus.ENABLED
    assert {
        capabilities.purchase.status,
        capabilities.payment.status,
        capabilities.top_up.status,
        capabilities.refund.status,
        capabilities.delivery.status,
    } == {CapabilityStatus.DISABLED}


def test_no_account_quote_order_money_write_or_delivery_operation_exists() -> None:
    allowed = {
        "list_products",
        "get_product",
        "get_wallet_balance",
        "list_wallet_transactions",
    }
    public_coroutines = {
        name
        for name, member in vars(RoboticvnReadAdapter).items()
        if not name.startswith("_") and inspect.iscoroutinefunction(member)
    }
    forbidden = {
        "get_account",
        "me",
        "quote",
        "create_quote",
        "orders",
        "list_orders",
        "order_history",
        "get_order",
        "payment_status",
        "purchase",
        "payment",
        "top_up",
        "topup",
        "refund",
        "delivery",
    }

    assert public_coroutines == allowed
    assert forbidden.isdisjoint(vars(RoboticvnReadAdapter))


def test_transport_is_required_and_has_no_concrete_default() -> None:
    parameters = inspect.signature(RoboticvnReadAdapter).parameters
    assert parameters["transport"].default is inspect.Parameter.empty
    assert parameters["api_key"].default is inspect.Parameter.empty


@pytest.mark.parametrize(
    "url,headers",
    [
        (PRODUCTION_ORIGIN + "/api/v2/me", {GLOBAL_AUTH_HEADER: "synthetic"}),
        (PRODUCTION_ORIGIN + "/api/v2/orders", {GLOBAL_AUTH_HEADER: "synthetic"}),
        (PRODUCTION_ORIGIN + "/api/v2/products/%252f", {GLOBAL_AUTH_HEADER: "synthetic"}),
        (
            PRODUCTION_ORIGIN + "/api/v2/products?x-api-key=url-secret",
            {GLOBAL_AUTH_HEADER: "synthetic"},
        ),
        ("https://example.invalid/api/v2/products", {GLOBAL_AUTH_HEADER: "synthetic"}),
        (PRODUCTION_ORIGIN + "/api/v2/products", {"Authorization": "synthetic"}),
        (
            PRODUCTION_ORIGIN + "/api/v2/products",
            {GLOBAL_AUTH_HEADER: "synthetic", "Accept": "application/json"},
        ),
    ],
)
def test_raw_request_model_cannot_construct_an_unauthorized_or_misplaced_key_target(
    url: str,
    headers: dict[str, str],
) -> None:
    with pytest.raises(RoboticvnConfigurationError) as caught:
        RoboticvnRequest(method="GET", url=url, headers=headers)
    assert "url-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "segment",
    [
        "\uff052e",
        "\uff05252e",
        "%ef%bc%852e",
        "%25ef%25bc%25852e",
        "safe\uff052funsafe",
        "safe\uff055cunsafe",
    ],
)
def test_raw_request_rejects_nfkc_percent_decode_path_escapes(segment: str) -> None:
    with pytest.raises(RoboticvnConfigurationError):
        RoboticvnRequest(
            method="GET",
            url=PRODUCTION_ORIGIN + "/api/v2/products/" + segment,
            headers={GLOBAL_AUTH_HEADER: "synthetic"},
        )


@pytest.mark.asyncio
async def test_injected_fake_transport_cannot_open_outbound_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("outbound network attempted")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    transport = FakeTransport([RoboticvnResponse(200, products_body())])

    outcome = await adapter(transport).list_products()

    assert isinstance(outcome, ReadSuccess)
    assert len(transport.requests) == 1
