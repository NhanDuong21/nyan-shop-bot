"""Strict, redaction-safe value objects for the VietShare read adapter."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal


class VietShareConfigurationError(ValueError):
    """A safe configuration error that never includes rejected input values."""


class ResponseValidationError(ValueError):
    """A safe description of an invalid product-list response."""

    def __init__(self, location: str, problem: str) -> None:
        self.location = location
        self.problem = problem
        super().__init__(f"Invalid VietShare product-list response at {location}: {problem}.")


def _require_text(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise VietShareConfigurationError(f"{label} must be a string")
    if not value:
        raise VietShareConfigurationError(f"{label} must not be empty")
    if "\r" in value or "\n" in value:
        raise VietShareConfigurationError(f"{label} must not contain line breaks")
    return value


@dataclass(frozen=True, repr=False)
class VietShareCredentials:
    """Signing credentials whose representation never reveals either value."""

    api_id: str = field(repr=False)
    api_secret: str | bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.api_id, label="API ID")
        if type(self.api_secret) is str:
            if not self.api_secret:
                raise VietShareConfigurationError("API secret must not be empty")
        elif type(self.api_secret) is bytes:
            if not self.api_secret:
                raise VietShareConfigurationError("API secret must not be empty")
        else:
            raise VietShareConfigurationError("API secret must be text or bytes")

    @property
    def secret_bytes(self) -> bytes:
        """Return the exact key bytes used by HMAC."""
        if isinstance(self.api_secret, bytes):
            return self.api_secret
        return self.api_secret.encode("utf-8")

    def __repr__(self) -> str:
        return "VietShareCredentials(api_id=<redacted>, api_secret=<redacted>)"


class SensitiveHeaders(Mapping[str, str]):
    """An immutable header mapping with a fully redacted representation."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, str]) -> None:
        copied: dict[str, str] = {}
        for name, value in values.items():
            if type(name) is not str or type(value) is not str:
                raise VietShareConfigurationError("HTTP headers must contain text names and values")
            if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
                raise VietShareConfigurationError("HTTP headers must not contain line breaks")
            copied[name] = value
        self._values = MappingProxyType(copied)

    def __getitem__(self, key: str) -> str:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return "SensitiveHeaders(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True, repr=False)
class VietShareRequest:
    """Exact outbound bytes and target captured without repr disclosure."""

    method: str
    url: str = field(repr=False)
    path_with_query: str = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if type(self.method) is not str or not self.method:
            raise VietShareConfigurationError("HTTP method must be non-empty text")
        if type(self.url) is not str or type(self.path_with_query) is not str:
            raise VietShareConfigurationError("Request target must be text")
        if type(self.body) is not bytes:
            raise VietShareConfigurationError("Request body must be exact bytes")
        object.__setattr__(self, "headers", SensitiveHeaders(self.headers))

    def __repr__(self) -> str:
        return (
            f"VietShareRequest(method={self.method!r}, url=<redacted>, "
            "path_with_query=<redacted>, headers=<redacted>, body=<redacted>)"
        )


@dataclass(frozen=True, repr=False)
class VietShareResponse:
    """A transport response that never prints headers or response content."""

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    body: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise VietShareConfigurationError("HTTP status code must be an integer from 100 to 599")
        if type(self.body) is not bytes:
            raise VietShareConfigurationError("Response body must be exact bytes")
        object.__setattr__(self, "headers", SensitiveHeaders(self.headers))

    def __repr__(self) -> str:
        return (
            f"VietShareResponse(status_code={self.status_code}, "
            "headers=<redacted>, body=<redacted>)"
        )


@dataclass(frozen=True, repr=False)
class VndMoney:
    """A VietShare integer VND price with explicit currency and storage unit."""

    amount_minor: int
    currency: Literal["VND"] = field(default="VND", init=False)
    unit: Literal["minor"] = field(default="minor", init=False)

    def __post_init__(self) -> None:
        if type(self.amount_minor) is not int or self.amount_minor < 0:
            raise ResponseValidationError("price", "expected a non-negative integer VND amount")

    def __repr__(self) -> str:
        return "VndMoney(amount_minor=<redacted>, currency='VND', unit='minor')"


@dataclass(frozen=True, repr=False)
class VietShareProduct:
    """The complete and only documented VietShare product-list item shape."""

    id: int
    name: str = field(repr=False)
    description: str = field(repr=False)
    price: VndMoney = field(repr=False)
    flash_sale_id: int | None
    stock: int
    allow_quantity: bool
    max_quantity: int

    def __post_init__(self) -> None:
        if type(self.id) is not int:
            raise ResponseValidationError("id", "expected an integer")
        if type(self.name) is not str:
            raise ResponseValidationError("name", "expected a string")
        if type(self.description) is not str:
            raise ResponseValidationError("description", "expected a string")
        if not isinstance(self.price, VndMoney):
            raise ResponseValidationError("price", "expected an integer VND amount")
        if self.flash_sale_id is not None and type(self.flash_sale_id) is not int:
            raise ResponseValidationError("flash_sale_id", "expected an integer or null")
        if type(self.stock) is not int or self.stock < 0:
            raise ResponseValidationError("stock", "expected a non-negative integer")
        if type(self.allow_quantity) is not bool:
            raise ResponseValidationError("allow_quantity", "expected a boolean")
        if type(self.max_quantity) is not int or self.max_quantity <= 0:
            raise ResponseValidationError("max_quantity", "expected a positive integer")

    @property
    def price_vnd(self) -> int:
        """Expose the documented supplier amount while retaining explicit currency."""
        return self.price.amount_minor

    def __repr__(self) -> str:
        return "VietShareProduct(<redacted>)"


@dataclass(frozen=True, repr=False)
class VietShareProductList:
    """The strict, non-paginated product-list response."""

    count: int
    products: tuple[VietShareProduct, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.count) is not int or self.count < 0:
            raise ResponseValidationError("count", "expected a non-negative integer")
        if type(self.products) is not tuple or not all(
            isinstance(product, VietShareProduct) for product in self.products
        ):
            raise ResponseValidationError("products", "expected a list of products")
        if self.count != len(self.products):
            raise ResponseValidationError("count", "did not match the product list length")

    def __repr__(self) -> str:
        return f"VietShareProductList(count={self.count}, products=<redacted>)"


class ProductListErrorCode(StrEnum):
    """Safe product-list failure categories."""

    HTTP_ERROR = "http_error"
    INVALID_RESPONSE = "invalid_response"
    TRANSPORT_ERROR = "transport_error"
    CONFIGURATION_ERROR = "configuration_error"
    RETRY_ERROR = "retry_error"


@dataclass(frozen=True, repr=False)
class ProductListSuccess:
    """A parsed supplier response."""

    value: VietShareProductList = field(repr=False)
    attempts: int
    status: Literal["success"] = field(default="success", init=False)

    def __repr__(self) -> str:
        return (
            f"ProductListSuccess(status='success', attempts={self.attempts}, "
            f"count={self.value.count}, value=<redacted>)"
        )


@dataclass(frozen=True)
class ProductListTimeout:
    """All bounded attempts ended in a read timeout."""

    attempts: int
    status: Literal["timeout"] = field(default="timeout", init=False)
    retryable: Literal[True] = field(default=True, init=False)


@dataclass(frozen=True)
class ProductListRateLimited:
    """All bounded attempts ended with HTTP 429."""

    attempts: int
    retry_after_seconds: float | None
    status: Literal["rate_limited"] = field(default="rate_limited", init=False)
    retryable: Literal[True] = field(default=True, init=False)


@dataclass(frozen=True)
class ProductListError:
    """A safe non-success outcome that contains no supplier payload."""

    code: ProductListErrorCode
    attempts: int
    status_code: int | None = None
    status: Literal["error"] = field(default="error", init=False)
    retryable: bool = False


type ProductListOutcome = (
    ProductListSuccess | ProductListTimeout | ProductListRateLimited | ProductListError
)


class UnsupportedReadOperation(StrEnum):
    """Known endpoints whose returned projection is absent from the snapshot."""

    ACCOUNT = "account"
    PRODUCT_DETAIL = "product_detail"
    STOCK_DETAIL = "stock_detail"
    PRODUCTS_PAGINATION = "products_pagination"


@dataclass(frozen=True)
class UnsupportedRead:
    """An explicit non-retryable gap; no transport call was made."""

    operation: UnsupportedReadOperation
    reason: str
    status: Literal["unsupported"] = field(default="unsupported", init=False)
    retryable: Literal[False] = field(default=False, init=False)


_TOP_LEVEL_FIELDS = frozenset({"count", "products"})
_PRODUCT_FIELDS = frozenset(
    {
        "id",
        "name",
        "description",
        "price",
        "flash_sale_id",
        "stock",
        "allow_quantity",
        "max_quantity",
    }
)


class _DuplicateJsonField(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonField
        result[key] = value
    return result


def _strict_int(value: object, *, location: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        qualifier = "non-negative " if minimum == 0 else "positive " if minimum == 1 else ""
        raise ResponseValidationError(location, f"expected a {qualifier}integer")
    return value


def _strict_string(value: object, *, location: str) -> str:
    if type(value) is not str:
        raise ResponseValidationError(location, "expected a string")
    return value


def _parse_product(value: object, *, index: int) -> VietShareProduct:
    location = f"products[{index}]"
    if type(value) is not dict:
        raise ResponseValidationError(location, "expected an object")
    if set(value) != _PRODUCT_FIELDS:
        raise ResponseValidationError(location, "expected exactly the documented fields")

    flash_sale_id = value["flash_sale_id"]
    if flash_sale_id is not None and type(flash_sale_id) is not int:
        raise ResponseValidationError(f"{location}.flash_sale_id", "expected an integer or null")
    allow_quantity = value["allow_quantity"]
    if type(allow_quantity) is not bool:
        raise ResponseValidationError(f"{location}.allow_quantity", "expected a boolean")

    price = _strict_int(value["price"], location=f"{location}.price", minimum=0)
    return VietShareProduct(
        id=_strict_int(value["id"], location=f"{location}.id"),
        name=_strict_string(value["name"], location=f"{location}.name"),
        description=_strict_string(value["description"], location=f"{location}.description"),
        price=VndMoney(amount_minor=price),
        flash_sale_id=flash_sale_id,
        stock=_strict_int(value["stock"], location=f"{location}.stock", minimum=0),
        allow_quantity=allow_quantity,
        max_quantity=_strict_int(
            value["max_quantity"], location=f"{location}.max_quantity", minimum=1
        ),
    )


def parse_product_list(raw_body: bytes) -> VietShareProductList:
    """Parse only the documented single-page product response, with no coercion."""
    if type(raw_body) is not bytes:
        raise ResponseValidationError("body", "expected exact response bytes")
    try:
        decoded: Any = json.loads(raw_body, object_pairs_hook=_object_without_duplicates)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ResponseValidationError("body", "expected unique-field UTF-8 JSON") from None

    if type(decoded) is not dict:
        raise ResponseValidationError("body", "expected an object")
    if set(decoded) != _TOP_LEVEL_FIELDS:
        raise ResponseValidationError("body", "expected exactly count and products")

    raw_products = decoded["products"]
    if type(raw_products) is not list:
        raise ResponseValidationError("products", "expected a list")
    products = tuple(
        _parse_product(product, index=index) for index, product in enumerate(raw_products)
    )
    count = _strict_int(decoded["count"], location="count", minimum=0)
    return VietShareProductList(count=count, products=products)
