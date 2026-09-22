"""Bounded HTTPS transport for KhoMMO's three approved GET-only routes."""

from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlsplit

import httpx

from nyan_shop_bot.suppliers.khommo.models import KhoMmoRequest, KhoMmoResponse

_HOST = "api.khommo.vn"
_API_PREFIX = "/api/partner/v1"
_DETAIL_PREFIX = f"{_API_PREFIX}/products/"


class KhoMmoTransportSafetyError(RuntimeError):
    """A safe transport failure that never includes URL, token, or response data."""


class KhoMmoHttpTransport:
    """Use TLS without redirects, ambient proxies, writes, or unbounded responses."""

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
        return "KhoMmoHttpTransport(host=<fixed>, credentials=<redacted>)"

    @staticmethod
    def _validate_request(request: KhoMmoRequest) -> None:
        if request.method != "GET":
            raise KhoMmoTransportSafetyError("KhoMMO transport permits GET only")

        parsed = urlsplit(request.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _HOST
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise KhoMmoTransportSafetyError("KhoMMO request target is not approved")

        if parsed.path == f"{_API_PREFIX}/me":
            if parsed.query:
                raise KhoMmoTransportSafetyError("KhoMMO account query is not approved")
        elif parsed.path == f"{_API_PREFIX}/products":
            query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            keys = [key for key, _ in query]
            if keys not in (["page", "limit"], ["page", "limit", "search"]):
                raise KhoMmoTransportSafetyError("KhoMMO products query is not approved")
        elif parsed.path.startswith(_DETAIL_PREFIX):
            identifier = unquote(parsed.path.removeprefix(_DETAIL_PREFIX))
            if not identifier or identifier in {".", ".."} or "/" in identifier or parsed.query:
                raise KhoMmoTransportSafetyError("KhoMMO product detail target is not approved")
        else:
            raise KhoMmoTransportSafetyError("KhoMMO route is not approved")

        if set(request.headers) != {"Authorization"}:
            raise KhoMmoTransportSafetyError("KhoMMO authorization header is invalid")
        authorization = request.headers["Authorization"]
        if (
            not authorization.startswith("Bearer ")
            or len(authorization) == len("Bearer ")
            or "\r" in authorization
            or "\n" in authorization
        ):
            raise KhoMmoTransportSafetyError("KhoMMO authorization header is invalid")

    async def send(
        self,
        request: KhoMmoRequest,
        *,
        timeout_seconds: float,
    ) -> KhoMmoResponse:
        self._validate_request(request)
        try:
            outbound = self._client.build_request(
                "GET",
                request.url,
                headers=dict(request.headers),
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
                        raise KhoMmoTransportSafetyError(
                            "KhoMMO response exceeded the configured size limit"
                        )
                    body.extend(chunk)
                return KhoMmoResponse(status_code=response.status_code, body=bytes(body))
            finally:
                await response.aclose()
        except httpx.TimeoutException:
            raise TimeoutError("KhoMMO read timed out") from None
        except httpx.HTTPError:
            raise KhoMmoTransportSafetyError("KhoMMO HTTPS transport failed") from None

    async def aclose(self) -> None:
        """Close only the production client created by this transport."""
        if self._owns_client:
            await self._client.aclose()
