"""Offline-testable, read-only VietShare v1 adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Protocol

from nyan_shop_bot.catalog.models import Capability, CapabilityStatus, SupplierCapabilities
from nyan_shop_bot.suppliers.vietshare.models import (
    ProductDetailNotFound,
    ProductDetailOutcome,
    ProductDetailSuccess,
    ProductListError,
    ProductListErrorCode,
    ProductListOutcome,
    ProductListRateLimited,
    ProductListSuccess,
    ProductListTimeout,
    ResponseValidationError,
    UnsupportedRead,
    UnsupportedReadOperation,
    VietShareConfigurationError,
    VietShareCredentials,
    VietShareRequest,
    VietShareResponse,
    parse_product_detail,
    parse_product_list,
)
from nyan_shop_bot.suppliers.vietshare.signing import (
    PRODUCTION_BASE_URL,
    build_signed_read_request,
)


class VietShareTransport(Protocol):
    """Injected byte transport; this package provides no socket implementation."""

    async def send(
        self, request: VietShareRequest, *, timeout_seconds: float
    ) -> VietShareResponse: ...


type Clock = Callable[[], int | float]
type NonceSource = Callable[[], str]
type RetrySleeper = Callable[[float], Awaitable[None]]


_STOCK_DETAIL_REASON = "The VietShare stock alias is outside this live-read milestone."
_ACCOUNT_REASON = "The supplied VietShare snapshot does not define an account response schema."
_PAGINATION_REASON = (
    "The supplied VietShare snapshot does not define product pagination parameters."
)
_WRITE_REASON = "This VietShare adapter is read-only; the operation is disabled."


VIETSHARE_CAPABILITIES = SupplierCapabilities(
    catalog_read=Capability(status=CapabilityStatus.ENABLED, reason=None),
    catalog_detail=Capability(status=CapabilityStatus.ENABLED, reason=None),
    purchase=Capability(status=CapabilityStatus.DISABLED, reason=_WRITE_REASON),
    payment=Capability(status=CapabilityStatus.DISABLED, reason=_WRITE_REASON),
    top_up=Capability(status=CapabilityStatus.DISABLED, reason=_WRITE_REASON),
    refund=Capability(status=CapabilityStatus.DISABLED, reason=_WRITE_REASON),
    delivery=Capability(status=CapabilityStatus.DISABLED, reason=_WRITE_REASON),
)


@dataclass(frozen=True)
class _RawReadSuccess:
    response: VietShareResponse
    attempts: int


type _RawReadOutcome = (
    _RawReadSuccess | ProductListTimeout | ProductListRateLimited | ProductListError
)


def _require_non_negative_int(value: int, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise VietShareConfigurationError(f"{label} must be a non-negative integer")
    return value


def _require_non_negative_number(value: float, *, label: str, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise VietShareConfigurationError(f"{label} must be a number")
    result = float(value)
    if result < 0 or (positive and result == 0):
        comparison = "positive" if positive else "non-negative"
        raise VietShareConfigurationError(f"{label} must be {comparison}")
    if result == float("inf") or result != result:
        raise VietShareConfigurationError(f"{label} must be finite")
    return result


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.casefold()
    for candidate, value in headers.items():
        if candidate.casefold() == wanted:
            return value
    return None


def parse_retry_after(value: str | None, *, now: int | float) -> float | None:
    """Parse an HTTP delta-seconds or HTTP-date Retry-After value safely."""
    if value is None or type(value) is not str:
        return None
    stripped = value.strip()
    if stripped.isascii() and stripped.isdecimal():
        try:
            return float(int(stripped))
        except (ValueError, OverflowError):
            return None
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    try:
        delay = parsed.timestamp() - float(now)
    except (OSError, OverflowError, ValueError):
        return None
    return max(0.0, delay)


class VietShareReadAdapter:
    """The supported product-list projection with bounded, read-only retries."""

    capabilities = VIETSHARE_CAPABILITIES

    def __init__(
        self,
        *,
        credentials: VietShareCredentials,
        transport: VietShareTransport,
        clock: Clock,
        nonce_source: NonceSource,
        retry_sleeper: RetrySleeper,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.0,
    ) -> None:
        self._credentials = credentials
        self._transport = transport
        self._clock = clock
        self._nonce_source = nonce_source
        self._retry_sleeper = retry_sleeper
        self._timeout_seconds = _require_non_negative_number(
            timeout_seconds, label="Timeout", positive=True
        )
        self._max_retries = _require_non_negative_int(max_retries, label="Maximum retries")
        self._retry_delay_seconds = _require_non_negative_number(
            retry_delay_seconds, label="Retry delay"
        )
        self._used_nonces: set[str] = set()
        self._nonce_lock = Lock()

    def __repr__(self) -> str:
        return (
            "VietShareReadAdapter(credentials=<redacted>, transport=<injected>, "
            f"base_url=<redacted>, timeout_seconds={self._timeout_seconds}, "
            f"max_retries={self._max_retries})"
        )

    @property
    def account_projection(self) -> UnsupportedRead:
        """Report the account schema gap without sending a request."""
        return UnsupportedRead(
            operation=UnsupportedReadOperation.ACCOUNT,
            reason=_ACCOUNT_REASON,
        )

    @property
    def stock_detail_projection(self) -> UnsupportedRead:
        """Report the stock-detail alias schema gap without sending a request."""
        return UnsupportedRead(
            operation=UnsupportedReadOperation.STOCK_DETAIL,
            reason=_STOCK_DETAIL_REASON,
        )

    @property
    def pagination(self) -> UnsupportedRead:
        """Report that no page, cursor, or limit contract is known."""
        return UnsupportedRead(
            operation=UnsupportedReadOperation.PRODUCTS_PAGINATION,
            reason=_PAGINATION_REASON,
        )

    async def get_account(self) -> UnsupportedRead:
        """Return the explicit schema gap; account payloads are never fetched."""
        return self.account_projection

    async def get_product(self, product_id: int) -> ProductDetailOutcome:
        """Read the observed direct product-detail object through the GET-only boundary."""
        if type(product_id) is not int or product_id <= 0:
            raise VietShareConfigurationError("Product ID must be a positive integer")
        raw = await self._read_response(endpoint=f"/products/{product_id}")
        if not isinstance(raw, _RawReadSuccess):
            return raw

        response = raw.response
        if response.status_code == 404:
            return ProductDetailNotFound(attempts=raw.attempts)
        if not 200 <= response.status_code <= 299:
            return ProductListError(
                code=ProductListErrorCode.HTTP_ERROR,
                attempts=raw.attempts,
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )
        try:
            product = parse_product_detail(response.body)
        except ResponseValidationError:
            return ProductListError(
                code=ProductListErrorCode.INVALID_RESPONSE,
                attempts=raw.attempts,
            )
        if product.id != product_id:
            return ProductListError(
                code=ProductListErrorCode.INVALID_RESPONSE,
                attempts=raw.attempts,
            )
        return ProductDetailSuccess(value=product, attempts=raw.attempts)

    async def get_stock(self, product_id: int) -> UnsupportedRead:
        """Return the explicit detail-alias gap without transmitting the id."""
        del product_id
        return self.stock_detail_projection

    async def list_products(self) -> ProductListOutcome:
        """Read the one documented, unpaginated ``/v1/products`` response."""
        return await self._read_product_list(endpoint="/products")

    async def list_catalog(self) -> ProductListOutcome:
        """Read the documented ``/v1/catalog`` alias with the same strict schema."""
        return await self._read_product_list(endpoint="/catalog")

    def _timestamp(self) -> int:
        value = self._clock()
        if type(value) not in (int, float):
            raise VietShareConfigurationError("Clock must return Unix seconds")
        numeric = float(value)
        if numeric < 0 or numeric == float("inf") or numeric != numeric:
            raise VietShareConfigurationError("Clock must return finite non-negative Unix seconds")
        return int(numeric)

    def _nonce(self) -> str:
        nonce = self._nonce_source()
        if type(nonce) is not str or not 12 <= len(nonce) <= 128:
            raise VietShareConfigurationError("Nonce source must return 12 to 128 characters")
        if "\r" in nonce or "\n" in nonce:
            raise VietShareConfigurationError("Nonce source must not return line breaks")
        with self._nonce_lock:
            if nonce in self._used_nonces:
                raise VietShareConfigurationError("Nonce source reused a nonce")
            self._used_nonces.add(nonce)
        return nonce

    def _request(self, *, endpoint: str) -> tuple[VietShareRequest, int]:
        timestamp = self._timestamp()
        nonce = self._nonce()
        request = build_signed_read_request(
            credentials=self._credentials,
            base_url=PRODUCTION_BASE_URL,
            endpoint=endpoint,
            timestamp=timestamp,
            nonce=nonce,
            query=(),
            raw_body=b"",
        )
        return request, timestamp

    async def _sleep_for_retry(self, delay: float, *, attempts: int) -> ProductListError | None:
        try:
            await self._retry_sleeper(delay)
        except Exception:
            return ProductListError(
                code=ProductListErrorCode.RETRY_ERROR,
                attempts=attempts,
            )
        return None

    async def _read_response(self, *, endpoint: str) -> _RawReadOutcome:
        total_attempts = self._max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                request, timestamp = self._request(endpoint=endpoint)
            except Exception:
                return ProductListError(
                    code=ProductListErrorCode.CONFIGURATION_ERROR,
                    attempts=attempt,
                )

            try:
                response = await self._transport.send(
                    request,
                    timeout_seconds=self._timeout_seconds,
                )
            except TimeoutError:
                if attempt == total_attempts:
                    return ProductListTimeout(attempts=attempt)
                sleep_error = await self._sleep_for_retry(
                    self._retry_delay_seconds,
                    attempts=attempt,
                )
                if sleep_error is not None:
                    return sleep_error
                continue
            except Exception:
                return ProductListError(
                    code=ProductListErrorCode.TRANSPORT_ERROR,
                    attempts=attempt,
                )

            if not isinstance(response, VietShareResponse):
                return ProductListError(
                    code=ProductListErrorCode.TRANSPORT_ERROR,
                    attempts=attempt,
                )

            if response.status_code == 429:
                retry_after = parse_retry_after(
                    _header(response.headers, "Retry-After"),
                    now=timestamp,
                )
                if attempt == total_attempts:
                    return ProductListRateLimited(
                        attempts=attempt,
                        retry_after_seconds=retry_after,
                    )
                sleep_error = await self._sleep_for_retry(
                    retry_after if retry_after is not None else self._retry_delay_seconds,
                    attempts=attempt,
                )
                if sleep_error is not None:
                    return sleep_error
                continue

            return _RawReadSuccess(response=response, attempts=attempt)

        raise AssertionError("bounded retry loop must return an outcome")

    async def _read_product_list(self, *, endpoint: str) -> ProductListOutcome:
        raw = await self._read_response(endpoint=endpoint)
        if not isinstance(raw, _RawReadSuccess):
            return raw

        response = raw.response
        if not 200 <= response.status_code <= 299:
            return ProductListError(
                code=ProductListErrorCode.HTTP_ERROR,
                attempts=raw.attempts,
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )
        try:
            products = parse_product_list(response.body)
        except ResponseValidationError:
            return ProductListError(
                code=ProductListErrorCode.INVALID_RESPONSE,
                attempts=raw.attempts,
            )
        return ProductListSuccess(value=products, attempts=raw.attempts)
