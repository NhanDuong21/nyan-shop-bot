"""Offline retry, capability, redaction, and network-boundary tests."""

from __future__ import annotations

import inspect
import json
import logging
import socket
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest

from nyan_shop_bot.catalog.models import CapabilityStatus
from nyan_shop_bot.suppliers.vietshare import (
    PRODUCTION_BASE_URL,
    ProductListError,
    ProductListErrorCode,
    ProductListRateLimited,
    ProductListSuccess,
    ProductListTimeout,
    UnsupportedReadOperation,
    VietShareCredentials,
    VietShareReadAdapter,
    VietShareRequest,
    VietShareResponse,
    parse_retry_after,
    sign_request,
)


def product_body(*, name: str = "Synthetic offline item") -> bytes:
    return json.dumps(
        {
            "count": 1,
            "products": [
                {
                    "id": 11,
                    "name": name,
                    "description": "Fixture content only.",
                    "price": 25_000,
                    "flash_sale_id": None,
                    "stock": 4,
                    "allow_quantity": True,
                    "max_quantity": 2,
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


class FakeTransport:
    def __init__(self, outcomes: Iterable[VietShareResponse | Exception]) -> None:
        self._outcomes = iter(outcomes)
        self.requests: list[VietShareRequest] = []
        self.timeouts: list[float] = []

    async def send(self, request: VietShareRequest, *, timeout_seconds: float) -> VietShareResponse:
        self.requests.append(request)
        self.timeouts.append(timeout_seconds)
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SequenceClock:
    def __init__(self, values: Iterable[int]) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        return next(self._values)


class SequenceNonce:
    def __init__(self, values: Iterable[str]) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return next(self._values)


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_adapter(
    transport: FakeTransport,
    *,
    clock_values: Iterable[int] = (1_760_000_000,),
    nonces: Iterable[str] = ("nonce-default-0001",),
    sleeper: RecordingSleeper | None = None,
    max_retries: int = 0,
    retry_delay_seconds: float = 0.25,
    api_id: str = "synthetic-shop-id",
    api_secret: str = "synthetic-shop-secret",
) -> tuple[VietShareReadAdapter, SequenceClock, SequenceNonce, RecordingSleeper]:
    clock = SequenceClock(clock_values)
    nonce_source = SequenceNonce(nonces)
    actual_sleeper = sleeper or RecordingSleeper()
    adapter = VietShareReadAdapter(
        credentials=VietShareCredentials(api_id=api_id, api_secret=api_secret),
        transport=transport,
        clock=clock,
        nonce_source=nonce_source,
        retry_sleeper=actual_sleeper,
        timeout_seconds=3.5,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    return adapter, clock, nonce_source, actual_sleeper


@pytest.mark.asyncio
async def test_product_read_emits_no_invented_pagination_query() -> None:
    transport = FakeTransport([VietShareResponse(status_code=200, body=product_body())])
    adapter, _, _, sleeper = make_adapter(transport)

    outcome = await adapter.list_products()

    assert isinstance(outcome, ProductListSuccess)
    assert outcome.value.count == 1
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url == PRODUCTION_BASE_URL + "/products"
    assert request.path_with_query == "/v1/products"
    assert "?" not in request.url
    assert all(name not in request.url for name in ("page", "cursor", "limit"))
    assert sleeper.delays == []
    parameters = inspect.signature(VietShareReadAdapter.list_products).parameters
    assert set(parameters) == {"self"}


@pytest.mark.asyncio
async def test_catalog_alias_uses_v1_catalog_without_query() -> None:
    transport = FakeTransport([VietShareResponse(status_code=200, body=product_body())])
    adapter, _, _, _ = make_adapter(transport)

    outcome = await adapter.list_catalog()

    assert isinstance(outcome, ProductListSuccess)
    assert transport.requests[0].url == PRODUCTION_BASE_URL + "/catalog"
    assert transport.requests[0].path_with_query == "/v1/catalog"


@pytest.mark.asyncio
async def test_timeout_retry_refreshes_clock_nonce_and_signature() -> None:
    transport = FakeTransport(
        [
            TimeoutError("synthetic timeout payload must stay private"),
            VietShareResponse(status_code=200, body=product_body()),
        ]
    )
    adapter, clock, nonce_source, sleeper = make_adapter(
        transport,
        clock_values=(1_760_000_010, 1_760_000_011),
        nonces=("timeout-nonce-0001", "timeout-nonce-0002"),
        max_retries=1,
    )

    outcome = await adapter.list_products()

    assert isinstance(outcome, ProductListSuccess)
    assert outcome.attempts == 2
    assert clock.calls == 2
    assert nonce_source.calls == 2
    assert sleeper.delays == [0.25]
    assert transport.timeouts == [3.5, 3.5]
    first, second = transport.requests
    assert first.headers["X-Timestamp"] == "1760000010"
    assert second.headers["X-Timestamp"] == "1760000011"
    assert first.headers["X-Nonce"] == "timeout-nonce-0001"
    assert second.headers["X-Nonce"] == "timeout-nonce-0002"
    assert first.headers["X-Signature"] != second.headers["X-Signature"]
    for request in (first, second):
        assert request.headers["X-Signature"] == sign_request(
            api_secret="synthetic-shop-secret",
            timestamp=int(request.headers["X-Timestamp"]),
            nonce=request.headers["X-Nonce"],
            method="GET",
            path_with_query="/v1/products",
            raw_body=b"",
        )


@pytest.mark.asyncio
async def test_429_retry_respects_retry_after_and_refreshes_auth() -> None:
    transport = FakeTransport(
        [
            VietShareResponse(
                status_code=429,
                headers={"rEtRy-AfTeR": "7"},
                body=b"rate-limit-body-must-stay-private",
            ),
            VietShareResponse(status_code=200, body=product_body()),
        ]
    )
    adapter, clock, nonce_source, sleeper = make_adapter(
        transport,
        clock_values=(1_760_000_020, 1_760_000_021),
        nonces=("ratelimit-nonce-01", "ratelimit-nonce-02"),
        max_retries=1,
    )

    outcome = await adapter.list_products()

    assert isinstance(outcome, ProductListSuccess)
    assert outcome.attempts == 2
    assert clock.calls == 2
    assert nonce_source.calls == 2
    assert sleeper.delays == [7.0]
    first, second = transport.requests
    assert first.headers["X-Timestamp"] != second.headers["X-Timestamp"]
    assert first.headers["X-Nonce"] != second.headers["X-Nonce"]
    assert first.headers["X-Signature"] != second.headers["X-Signature"]


def test_retry_after_parses_delta_seconds_and_http_date() -> None:
    now = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
    future = now + timedelta(seconds=11)

    assert parse_retry_after(" 9 ", now=now.timestamp()) == 9.0
    assert (
        parse_retry_after(
            future.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            now=now.timestamp(),
        )
        == 11.0
    )
    assert parse_retry_after("-1", now=now.timestamp()) is None
    assert parse_retry_after("1.5", now=now.timestamp()) is None
    assert parse_retry_after("private-invalid-value", now=now.timestamp()) is None
    assert parse_retry_after("9" * 5_000, now=now.timestamp()) is None


@pytest.mark.asyncio
async def test_invalid_retry_after_uses_injected_fallback_without_real_sleep() -> None:
    transport = FakeTransport(
        [
            VietShareResponse(status_code=429, headers={"Retry-After": "invalid"}),
            VietShareResponse(status_code=200, body=product_body()),
        ]
    )
    adapter, _, _, sleeper = make_adapter(
        transport,
        clock_values=(100, 101),
        nonces=("invalid-retry-0001", "invalid-retry-0002"),
        max_retries=1,
        retry_delay_seconds=0.75,
    )

    outcome = await adapter.list_products()

    assert isinstance(outcome, ProductListSuccess)
    assert sleeper.delays == [0.75]


@pytest.mark.asyncio
async def test_exhausted_timeout_and_rate_limit_have_typed_outcomes() -> None:
    timeout_transport = FakeTransport([TimeoutError(), TimeoutError()])
    timeout_adapter, _, _, timeout_sleeper = make_adapter(
        timeout_transport,
        clock_values=(1, 2),
        nonces=("timeout-final-0001", "timeout-final-0002"),
        max_retries=1,
    )
    timeout_outcome = await timeout_adapter.list_products()

    rate_transport = FakeTransport(
        [
            VietShareResponse(status_code=429, headers={"Retry-After": "2"}),
            VietShareResponse(status_code=429, headers={"Retry-After": "5"}),
        ]
    )
    rate_adapter, _, _, rate_sleeper = make_adapter(
        rate_transport,
        clock_values=(3, 4),
        nonces=("rate-final-000001", "rate-final-000002"),
        max_retries=1,
    )
    rate_outcome = await rate_adapter.list_products()

    assert timeout_outcome == ProductListTimeout(attempts=2)
    assert timeout_sleeper.delays == [0.25]
    assert rate_outcome == ProductListRateLimited(attempts=2, retry_after_seconds=5.0)
    assert rate_sleeper.delays == [2.0]


@pytest.mark.asyncio
async def test_other_http_and_invalid_response_failures_are_typed_and_not_retried() -> None:
    http_transport = FakeTransport([VietShareResponse(status_code=503, body=b"private")])
    http_adapter, _, _, _ = make_adapter(
        http_transport,
        clock_values=(1, 2),
        nonces=("http-error-000001", "http-error-000002"),
        max_retries=1,
    )
    http_outcome = await http_adapter.list_products()

    invalid_transport = FakeTransport(
        [VietShareResponse(status_code=200, body=b"sensitive-invalid-json")]
    )
    invalid_adapter, _, _, _ = make_adapter(invalid_transport)
    invalid_outcome = await invalid_adapter.list_products()

    assert http_outcome == ProductListError(
        code=ProductListErrorCode.HTTP_ERROR,
        attempts=1,
        status_code=503,
        retryable=True,
    )
    assert len(http_transport.requests) == 1
    assert invalid_outcome == ProductListError(
        code=ProductListErrorCode.INVALID_RESPONSE,
        attempts=1,
    )
    assert "sensitive-invalid-json" not in repr(invalid_outcome)


@pytest.mark.asyncio
async def test_transport_errors_and_logs_do_not_disclose_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_id = "api-id-private-marker"
    api_secret = "api-secret-private-marker"
    transport = FakeTransport(
        [RuntimeError(f"transport included {api_id} and {api_secret} and response-private-marker")]
    )
    adapter, _, _, _ = make_adapter(
        transport,
        api_id=api_id,
        api_secret=api_secret,
    )

    with caplog.at_level(logging.DEBUG):
        outcome = await adapter.list_products()

    assert outcome == ProductListError(
        code=ProductListErrorCode.TRANSPORT_ERROR,
        attempts=1,
    )
    combined = repr(adapter) + repr(outcome) + caplog.text
    assert api_id not in combined
    assert api_secret not in combined
    assert "response-private-marker" not in combined


@pytest.mark.asyncio
async def test_reused_nonce_fails_closed_before_a_second_transport_call() -> None:
    transport = FakeTransport(
        [
            TimeoutError(),
            VietShareResponse(status_code=200, body=product_body()),
        ]
    )
    adapter, clock, nonce_source, _ = make_adapter(
        transport,
        clock_values=(10, 11),
        nonces=("reused-nonce-0001", "reused-nonce-0001"),
        max_retries=1,
    )

    outcome = await adapter.list_products()

    assert outcome == ProductListError(
        code=ProductListErrorCode.CONFIGURATION_ERROR,
        attempts=2,
    )
    assert clock.calls == 2
    assert nonce_source.calls == 2
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_unsupported_account_detail_and_pagination_never_call_transport() -> None:
    transport = FakeTransport([])
    adapter, _, _, _ = make_adapter(transport)

    account = await adapter.get_account()
    detail = await adapter.get_product(123)
    stock = await adapter.get_stock(123)
    pagination = adapter.pagination

    assert account.operation is UnsupportedReadOperation.ACCOUNT
    assert detail.operation is UnsupportedReadOperation.PRODUCT_DETAIL
    assert stock.operation is UnsupportedReadOperation.STOCK_DETAIL
    assert pagination.operation is UnsupportedReadOperation.PRODUCTS_PAGINATION
    assert all(result.status == "unsupported" for result in (account, detail, stock, pagination))
    assert all(not result.retryable for result in (account, detail, stock, pagination))
    assert transport.requests == []


def test_capabilities_enable_only_supported_catalog_list_reads() -> None:
    transport = FakeTransport([])
    adapter, _, _, _ = make_adapter(transport)
    capabilities = adapter.capabilities

    assert capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert capabilities.catalog_detail.status is CapabilityStatus.UNSUPPORTED
    assert {
        capabilities.purchase.status,
        capabilities.payment.status,
        capabilities.top_up.status,
        capabilities.refund.status,
        capabilities.delivery.status,
    } == {CapabilityStatus.DISABLED}


def test_adapter_exposes_no_money_order_or_delivery_operation() -> None:
    forbidden = {
        "create_order",
        "list_orders",
        "order_history",
        "purchase",
        "payment",
        "top_up",
        "refund",
        "delivery",
    }

    assert forbidden.isdisjoint(vars(VietShareReadAdapter))


@pytest.mark.asyncio
async def test_injected_transport_keeps_product_tests_off_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a VietShare test attempted outbound network access")

    monkeypatch.setattr(socket.socket, "connect", deny_connect)
    monkeypatch.setattr(socket, "create_connection", deny_connect)
    transport = FakeTransport([VietShareResponse(status_code=200, body=product_body())])
    adapter, _, _, _ = make_adapter(transport)

    outcome = await adapter.list_products()

    assert isinstance(outcome, ProductListSuccess)
    assert len(transport.requests) == 1
