"""Dependency-free KhoMMO adapter with injected transport and no socket implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import quote, urlencode

from nyan_shop_bot.catalog.models import Capability, CapabilityStatus, SupplierCapabilities
from nyan_shop_bot.suppliers.khommo.models import (
    KhoMmoConfigurationError,
    KhoMmoRequest,
    KhoMmoResponse,
    KhoMmoToken,
    OutcomeCode,
    ReadFailure,
    ReadOutcome,
    ReadSuccess,
    UnsupportedSchemaError,
    decode_json,
    parse_account,
    parse_product,
    parse_products,
)

PRODUCTION_BASE_URL = "https://api.khommo.vn/api/partner/v1"
_DISABLED = "KhoMMO integration is read-only; this operation is disabled."
KHOMMO_CAPABILITIES = SupplierCapabilities(
    catalog_read=Capability(status=CapabilityStatus.ENABLED, reason=None),
    catalog_detail=Capability(status=CapabilityStatus.ENABLED, reason=None),
    purchase=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED),
    payment=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED),
    top_up=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED),
    refund=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED),
    delivery=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED),
)


class KhoMmoTransport(Protocol):
    async def send(self, request: KhoMmoRequest, *, timeout_seconds: float) -> KhoMmoResponse: ...


type Sleeper = Callable[[float], Awaitable[None]]


class KhoMmoReadAdapter:
    capabilities = KHOMMO_CAPABILITIES

    def __init__(
        self,
        *,
        token: KhoMmoToken,
        transport: KhoMmoTransport,
        timeout_seconds: float = 10.0,
        sleeper: Sleeper | None = None,
    ) -> None:
        if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
            raise KhoMmoConfigurationError("Timeout must be a positive number")
        self._token = token
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)
        self._sleeper = sleeper  # deliberately unused: the supplier gives no retry guarantee

    def __repr__(self) -> str:
        return "KhoMmoReadAdapter(token=<redacted>, transport=<injected>, base_url=<redacted>)"

    def _request(self, path: str, query: tuple[tuple[str, str], ...] = ()) -> KhoMmoRequest:
        url = PRODUCTION_BASE_URL + path
        if query:
            url += "?" + urlencode(query)
        return KhoMmoRequest(
            method="GET", url=url, headers={"Authorization": f"Bearer {self._token.value}"}
        )

    async def _send(
        self, request: KhoMmoRequest, parser: Callable[[object], object]
    ) -> ReadOutcome:
        try:
            response = await self._transport.send(request, timeout_seconds=self._timeout_seconds)
        except TimeoutError:
            return ReadFailure(OutcomeCode.TIMEOUT)
        except Exception:
            return ReadFailure(OutcomeCode.TRANSPORT_ERROR)
        codes = {
            400: OutcomeCode.BAD_REQUEST,
            401: OutcomeCode.UNAUTHORIZED,
            404: OutcomeCode.NOT_FOUND,
            502: OutcomeCode.BAD_GATEWAY,
        }
        if response.status_code in codes:
            return ReadFailure(codes[response.status_code], response.status_code)
        if not 200 <= response.status_code < 300:
            return ReadFailure(OutcomeCode.TRANSPORT_ERROR, response.status_code)
        try:
            decoded = decode_json(response.body)
        except UnsupportedSchemaError as error:
            code = (
                OutcomeCode.MALFORMED_JSON
                if error.reason == "malformed JSON"
                else OutcomeCode.UNSUPPORTED_SCHEMA
            )
            return ReadFailure(code)
        try:
            return ReadSuccess(parser(decoded))  # type: ignore[arg-type]
        except UnsupportedSchemaError:
            return ReadFailure(OutcomeCode.UNSUPPORTED_SCHEMA)

    async def get_account(self) -> ReadOutcome:
        return await self._send(self._request("/me"), parse_account)

    async def list_products(
        self, *, page: int = 1, limit: int = 20, search: str | None = None
    ) -> ReadOutcome:
        if type(page) is not int or page < 1:
            raise KhoMmoConfigurationError("Page must be a positive integer")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise KhoMmoConfigurationError("Limit must be an integer from 1 through 500")
        query = [("page", str(page)), ("limit", str(limit))]
        if search is not None:
            if type(search) is not str:
                raise KhoMmoConfigurationError("Search must be text")
            query.append(("search", search))
        return await self._send(self._request("/products", tuple(query)), parse_products)

    async def get_product(self, product_id: str) -> ReadOutcome:
        if (
            type(product_id) is not str
            or not product_id
            or product_id in {".", ".."}
            or "/" in product_id
        ):
            raise KhoMmoConfigurationError("Product ID must be non-empty path-safe text")
        return await self._send(
            self._request("/products/" + quote(product_id, safe="")), parse_product
        )
