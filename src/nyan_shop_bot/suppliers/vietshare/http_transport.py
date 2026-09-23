"""Bounded HTTPS transport for the owner-approved VietShare GET-only routes."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx

from nyan_shop_bot.suppliers.vietshare.models import VietShareRequest, VietShareResponse

_HOST = "token.vietshare.site"
_DETAIL_PATH = re.compile(r"^/v1/products/[1-9][0-9]*$")
_READ_PATHS = frozenset({"/v1/account", "/v1/products"})
_AUTH_HEADERS = frozenset({"X-Shop-API-ID", "X-Timestamp", "X-Nonce", "X-Signature"})


class VietShareTransportSafetyError(RuntimeError):
    """A redaction-safe transport failure with no request or response values."""


class VietShareHttpTransport:
    """Use fixed-host TLS without redirects, ambient proxies, writes, or large responses."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be a positive integer")
        self._client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    def __repr__(self) -> str:
        return "VietShareHttpTransport(host=<fixed>, credentials=<redacted>)"

    @staticmethod
    def _validate_request(request: VietShareRequest) -> None:
        if request.method != "GET" or request.body != b"":
            raise VietShareTransportSafetyError("VietShare transport permits empty-body GET only")

        parsed = urlsplit(request.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _HOST
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or request.path_with_query != parsed.path
            or (parsed.path not in _READ_PATHS and _DETAIL_PATH.fullmatch(parsed.path) is None)
        ):
            raise VietShareTransportSafetyError("VietShare request target is not approved")

        if set(request.headers) != _AUTH_HEADERS:
            raise VietShareTransportSafetyError("VietShare authentication headers are invalid")
        for value in request.headers.values():
            if not value or "\r" in value or "\n" in value:
                raise VietShareTransportSafetyError("VietShare authentication headers are invalid")

    async def send(
        self,
        request: VietShareRequest,
        *,
        timeout_seconds: float,
    ) -> VietShareResponse:
        self._validate_request(request)
        try:
            outbound = self._client.build_request(
                "GET",
                request.url,
                headers=dict(request.headers),
                content=b"",
                timeout=timeout_seconds,
            )
            response = await self._client.send(
                outbound,
                stream=True,
                follow_redirects=False,
            )
            try:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > self._max_response_bytes:
                        raise VietShareTransportSafetyError(
                            "VietShare response exceeded the configured size limit"
                        )
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
            raise TimeoutError("VietShare read timed out") from None
        except httpx.HTTPError:
            raise VietShareTransportSafetyError("VietShare HTTPS transport failed") from None

    async def aclose(self) -> None:
        """Close only the production client created by this transport."""
        if self._owns_client:
            await self._client.aclose()
