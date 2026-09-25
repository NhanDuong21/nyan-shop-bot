"""The capped HTTP adapter uses an injected in-memory fake only."""

from __future__ import annotations

import httpx
import pytest

from nyan_shop_bot.suppliers.vietshare.capped_transport import (
    CappedTransportError,
    VietShareCappedOrderTransport,
)
from nyan_shop_bot.suppliers.vietshare.models import SensitiveHeaders, VietShareRequest


def request(
    *, method: str = "POST", url: str = "https://token.vietshare.site/v1/orders"
) -> VietShareRequest:
    return VietShareRequest(
        method=method,
        url=url,
        path_with_query="/v1/orders",
        headers=SensitiveHeaders(
            {
                "X-Shop-API-ID": "synthetic-id",
                "X-Timestamp": "1000",
                "X-Nonce": "synthetic-nonce-0001",
                "X-Signature": "a" * 64,
                "Idempotency-Key": "synthetic-key-one",
                "Content-Type": "application/json",
            }
        ),
        body=b'{"product_id":28,"quantity":1,"max_unit_price":5000,"currency":"VND"}',
    )


async def test_fixed_post_preserves_body_and_only_retry_after() -> None:
    seen: list[httpx.Request] = []

    def handler(outbound: httpx.Request) -> httpx.Response:
        seen.append(outbound)
        return httpx.Response(
            202,
            headers={"Retry-After": "3", "X-Supplier-Private": "do-not-return"},
            content=b'{"detail":{"code":"REQUEST_IN_PROGRESS"}}',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = VietShareCappedOrderTransport(client=client)
        outcome = await transport.send(request(), timeout_seconds=5)
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "https://token.vietshare.site/v1/orders"
    assert seen[0].content == request().body
    assert outcome.status_code == 202
    assert outcome.headers == {"Retry-After": "3"}
    assert "do-not-return" not in repr(outcome)


@pytest.mark.parametrize(
    "bad",
    [
        request(method="GET"),
        request(url="https://other.example/v1/orders"),
    ],
)
async def test_rejects_other_methods_and_destinations_before_fake_send(
    bad: VietShareRequest,
) -> None:
    calls = 0

    def handler(_outbound: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CappedTransportError):
            await VietShareCappedOrderTransport(client=client).send(bad, timeout_seconds=5)
    assert calls == 0


async def test_rejects_oversized_response_without_material_in_error() -> None:
    marker = b"synthetic-private-delivery"

    def handler(_outbound: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=marker * 10)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CappedTransportError) as error:
            await VietShareCappedOrderTransport(client=client, max_response_bytes=16).send(
                request(), timeout_seconds=5
            )
    assert marker.decode() not in str(error.value)
