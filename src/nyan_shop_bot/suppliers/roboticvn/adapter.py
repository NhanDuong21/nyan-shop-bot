"""Dependency-free Roboticvn v2 reads over an injected byte transport."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol
from urllib.parse import quote, unquote, urlencode

from nyan_shop_bot.catalog.models import Capability, CapabilityStatus, SupplierCapabilities
from nyan_shop_bot.suppliers.roboticvn.models import (
    MalformedJsonError,
    OutcomeCode,
    ReadFailure,
    ReadOutcome,
    ReadSuccess,
    ReadValue,
    RoboticvnApiKey,
    RoboticvnConfigurationError,
    RoboticvnRequest,
    RoboticvnResponse,
    UnsupportedSchemaError,
    parse_product_detail,
    parse_product_list,
    parse_wallet_balance,
    parse_wallet_transactions,
)
from nyan_shop_bot.suppliers.roboticvn.provenance import (
    API_PREFIX,
    GLOBAL_AUTH_HEADER,
    PRODUCTION_ORIGIN,
)

PRODUCTION_BASE_URL = PRODUCTION_ORIGIN

_DISABLED_REASON = "Roboticvn integration is read-only; this operation is disabled."
ROBOTICVN_CAPABILITIES = SupplierCapabilities(
    catalog_read=Capability(status=CapabilityStatus.ENABLED, reason=None),
    catalog_detail=Capability(status=CapabilityStatus.ENABLED, reason=None),
    purchase=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED_REASON),
    payment=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED_REASON),
    top_up=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED_REASON),
    refund=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED_REASON),
    delivery=Capability(status=CapabilityStatus.DISABLED, reason=_DISABLED_REASON),
)


class Locale(StrEnum):
    VIETNAMESE = "vi-VN"
    ENGLISH = "en-US"


class WalletCurrencyCode(StrEnum):
    VND = "vnd"
    USD = "usd"


class RoboticvnTransport(Protocol):
    """Injected transport contract; this package has no socket implementation."""

    async def send(
        self, request: RoboticvnRequest, *, timeout_seconds: float
    ) -> RoboticvnResponse: ...


def _positive_timeout(value: float) -> float:
    if type(value) not in (int, float):
        raise RoboticvnConfigurationError("Timeout must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise RoboticvnConfigurationError("Timeout must be a positive finite number")
    return result


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 100:
        raise RoboticvnConfigurationError("Limit must be an integer from 1 through 100")
    return value


def _offset(value: int) -> int:
    if type(value) is not int or value < 0:
        raise RoboticvnConfigurationError("Offset must be a non-negative integer")
    return value


def _optional_text(value: str | None, label: str) -> str | None:
    if value is not None and type(value) is not str:
        raise RoboticvnConfigurationError(f"{label} must be text when provided")
    return value


def _locale(value: str | Locale | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in {item.value for item in Locale}:
        raise RoboticvnConfigurationError("Locale must be vi-VN or en-US")
    return str(value)


def _currency(value: str | WalletCurrencyCode) -> str:
    if not isinstance(value, str) or value not in {item.value for item in WalletCurrencyCode}:
        raise RoboticvnConfigurationError("Currency code must be vnd or usd")
    return str(value)


def _contains_control(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)


def _reject_unsafe_segment_form(value: str) -> None:
    normalized = unicodedata.normalize("NFKC", value)
    for candidate in (value, normalized):
        if candidate in {".", ".."} or "/" in candidate or "\\" in candidate:
            raise RoboticvnConfigurationError("Product ID must be one non-empty, path-safe segment")
        if _contains_control(candidate):
            raise RoboticvnConfigurationError("Product ID must be one non-empty, path-safe segment")


def _encoded_product_id(value: str) -> str:
    if type(value) is not str or not value:
        raise RoboticvnConfigurationError("Product ID must be one non-empty, path-safe segment")

    candidate = value
    for _ in range(len(value) + 1):
        _reject_unsafe_segment_form(candidate)
        try:
            decoded = unquote(candidate, errors="strict")
        except UnicodeDecodeError:
            raise RoboticvnConfigurationError(
                "Product ID must be one non-empty, path-safe segment"
            ) from None
        if decoded == candidate:
            break
        candidate = decoded
    else:
        raise RoboticvnConfigurationError("Product ID must be one non-empty, path-safe segment")
    return quote(value, safe="")


class RoboticvnReadAdapter:
    """The four authorized Roboticvn v2 reads, with no retry or live transport."""

    capabilities = ROBOTICVN_CAPABILITIES

    def __init__(
        self,
        *,
        api_key: RoboticvnApiKey,
        transport: RoboticvnTransport,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isinstance(api_key, RoboticvnApiKey):
            raise RoboticvnConfigurationError("API key must use RoboticvnApiKey")
        self._api_key = api_key
        self._transport = transport
        self._timeout_seconds = _positive_timeout(timeout_seconds)

    def __repr__(self) -> str:
        return "RoboticvnReadAdapter(api_key=<redacted>, transport=<injected>, base_url=<redacted>)"

    def _request(self, path: str, query: tuple[tuple[str, str], ...] = ()) -> RoboticvnRequest:
        url = PRODUCTION_ORIGIN + path
        if query:
            url += "?" + urlencode(query)
        return RoboticvnRequest(
            method="GET",
            url=url,
            headers={GLOBAL_AUTH_HEADER: self._api_key.value},
        )

    async def _send(
        self,
        request: RoboticvnRequest,
        parser: Callable[[bytes], ReadValue],
    ) -> ReadOutcome:
        try:
            response = await self._transport.send(
                request,
                timeout_seconds=self._timeout_seconds,
            )
        except TimeoutError:
            return ReadFailure(OutcomeCode.TIMEOUT)
        except Exception:
            return ReadFailure(OutcomeCode.TRANSPORT_ERROR)

        if not isinstance(response, RoboticvnResponse):
            return ReadFailure(OutcomeCode.TRANSPORT_ERROR)
        status_codes = {
            400: OutcomeCode.BAD_REQUEST,
            401: OutcomeCode.UNAUTHORIZED,
            404: OutcomeCode.NOT_FOUND,
            429: OutcomeCode.RATE_LIMITED,
            500: OutcomeCode.SUPPLIER_ERROR,
        }
        if response.status_code in status_codes:
            return ReadFailure(status_codes[response.status_code], response.status_code)
        if response.status_code != 200:
            return ReadFailure(OutcomeCode.UNEXPECTED_STATUS, response.status_code)
        try:
            return ReadSuccess(parser(response.body))
        except MalformedJsonError:
            return ReadFailure(OutcomeCode.MALFORMED_JSON)
        except UnsupportedSchemaError:
            return ReadFailure(OutcomeCode.UNSUPPORTED_SCHEMA)

    async def list_products(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
        category_id: str | None = None,
        locale: str | Locale | None = None,
    ) -> ReadOutcome:
        query = [
            ("limit", str(_limit(limit))),
            ("offset", str(_offset(offset))),
        ]
        checked_search = _optional_text(search, "Search")
        if checked_search is not None:
            query.append(("search", checked_search))
        checked_category = _optional_text(category_id, "Category ID")
        if checked_category is not None:
            query.append(("category_id", checked_category))
        checked_locale = _locale(locale)
        if checked_locale is not None:
            query.append(("locale", checked_locale))
        return await self._send(
            self._request(f"{API_PREFIX}/products", tuple(query)),
            parse_product_list,
        )

    async def get_product(
        self,
        product_id: str,
        *,
        locale: str | Locale | None = None,
    ) -> ReadOutcome:
        encoded_id = _encoded_product_id(product_id)
        query: tuple[tuple[str, str], ...] = ()
        checked_locale = _locale(locale)
        if checked_locale is not None:
            query = (("locale", checked_locale),)
        return await self._send(
            self._request(f"{API_PREFIX}/products/{encoded_id}", query),
            parse_product_detail,
        )

    async def get_wallet_balance(
        self,
        *,
        locale: str | Locale | None = None,
    ) -> ReadOutcome:
        query: tuple[tuple[str, str], ...] = ()
        checked_locale = _locale(locale)
        if checked_locale is not None:
            query = (("locale", checked_locale),)
        return await self._send(
            self._request(f"{API_PREFIX}/wallet/balance", query),
            parse_wallet_balance,
        )

    async def list_wallet_transactions(
        self,
        *,
        currency_code: str | WalletCurrencyCode = "vnd",
        limit: int = 20,
        offset: int = 0,
        locale: str | Locale | None = None,
    ) -> ReadOutcome:
        query = [
            ("currency_code", _currency(currency_code)),
            ("limit", str(_limit(limit))),
            ("offset", str(_offset(offset))),
        ]
        checked_locale = _locale(locale)
        if checked_locale is not None:
            query.append(("locale", checked_locale))
        return await self._send(
            self._request(f"{API_PREFIX}/wallet/transactions", tuple(query)),
            parse_wallet_transactions,
        )
