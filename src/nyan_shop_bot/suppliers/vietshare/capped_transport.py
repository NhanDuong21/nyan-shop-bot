"""Fixed-target HTTPS POST transport for the separately armed capped test only."""

from __future__ import annotations

import re

import httpx

from nyan_shop_bot.suppliers.vietshare.models import VietShareRequest, VietShareResponse

_URL = "https://token.vietshare.site/v1/orders"
_HEADERS = frozenset(
    {
        "X-Shop-API-ID",
        "X-Timestamp",
        "X-Nonce",
        "X-Signature",
        "Idempotency-Key",
        "Content-Type",
    }
)


class CappedTransportError(RuntimeError):
    """Redacted target, response, or network failure."""


class VietShareCappedOrderTransport:
    """No generic write mode, alternate host, redirects, proxy, or other route."""

    def __init__(
        self, *, client: httpx.AsyncClient | None = None, max_response_bytes: int = 2_000_000
    ) -> None:
        if type(max_response_bytes) is not int or not 0 < max_response_bytes <= 2_000_000:
            raise ValueError("Invalid capped response limit")
        self._client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    def __repr__(self) -> str:
        return "VietShareCappedOrderTransport(<redacted>)"

    @staticmethod
    def _validate_request(request: VietShareRequest) -> None:
        if (
            not isinstance(request, VietShareRequest)
            or request.method != "POST"
            or request.url != _URL
            or request.path_with_query != "/v1/orders"
            or type(request.body) is not bytes
            or not 1 <= len(request.body) <= 4096
            or set(request.headers) != _HEADERS
            or request.headers["Content-Type"] != "application/json"
            or re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", request.headers["Idempotency-Key"]) is None
            or re.fullmatch(r"[0-9]{1,20}", request.headers["X-Timestamp"]) is None
            or re.fullmatch(r"[A-Za-z0-9._:-]{12,128}", request.headers["X-Nonce"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", request.headers["X-Signature"]) is None
            or not request.headers["X-Shop-API-ID"]
        ):
            raise CappedTransportError("Capped VietShare request is invalid")
        if any("\r" in value or "\n" in value for value in request.headers.values()):
            raise CappedTransportError("Capped VietShare headers are invalid")

    async def send(self, request: VietShareRequest, *, timeout_seconds: float) -> VietShareResponse:
        self._validate_request(request)
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 10:
            raise CappedTransportError("Capped VietShare timeout is invalid")
        try:
            outbound = self._client.build_request(
                "POST",
                _URL,
                headers=dict(request.headers),
                content=request.body,
                timeout=timeout_seconds,
            )
            response = await self._client.send(outbound, stream=True, follow_redirects=False)
            try:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > self._max_response_bytes:
                        raise CappedTransportError("Capped VietShare response exceeds limit")
                    body.extend(chunk)
                retry_after = response.headers.get("Retry-After")
                safe_headers = {"Retry-After": retry_after} if retry_after is not None else {}
                return VietShareResponse(
                    status_code=response.status_code,
                    headers=safe_headers,
                    body=bytes(body),
                )
            finally:
                await response.aclose()
        except httpx.TimeoutException:
            raise TimeoutError("Capped VietShare transport timed out") from None
        except httpx.HTTPError:
            raise CappedTransportError("Capped VietShare HTTPS transport failed") from None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
