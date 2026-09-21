"""Strict, redaction-safe models for the offline KhoMMO read adapter."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal


class KhoMmoConfigurationError(ValueError):
    """A configuration error that never echoes rejected values."""


class UnsupportedSchemaError(ValueError):
    """The response cannot be projected without guessing undocumented schema."""

    def __init__(self, location: str, reason: str) -> None:
        self.location = location
        self.reason = reason
        super().__init__(f"Unsupported KhoMMO schema at {location}: {reason}.")


@dataclass(frozen=True, repr=False)
class KhoMmoToken:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.value) is not str
            or not self.value
            or "\r" in self.value
            or "\n" in self.value
        ):
            raise KhoMmoConfigurationError(
                "Bearer token must be non-empty text without line breaks"
            )

    def __repr__(self) -> str:
        return "KhoMmoToken(<redacted>)"


class SensitiveHeaders(Mapping[str, str]):
    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = MappingProxyType(dict(values))

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
class KhoMmoRequest:
    method: Literal["GET"]
    url: str = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", SensitiveHeaders(self.headers))

    def __repr__(self) -> str:
        return "KhoMmoRequest(method='GET', url=<redacted>, headers=<redacted>)"


@dataclass(frozen=True, repr=False)
class KhoMmoResponse:
    status_code: int
    body: bytes = field(default=b"", repr=False)

    def __repr__(self) -> str:
        return f"KhoMmoResponse(status_code={self.status_code}, body=<redacted>)"


@dataclass(frozen=True)
class CreditUnits:
    amount: int
    unit: Literal["CREDIT"] = field(default="CREDIT", init=False)

    def __post_init__(self) -> None:
        if type(self.amount) is not int or self.amount < 0:
            raise UnsupportedSchemaError("CREDIT", "expected a non-negative integer")


@dataclass(frozen=True)
class VndUnits:
    amount: int
    unit: Literal["VND"] = field(default="VND", init=False)

    def __post_init__(self) -> None:
        if type(self.amount) is not int or self.amount < 0:
            raise UnsupportedSchemaError("VND", "expected a non-negative integer")


class PaymentMode(StrEnum):
    CREDIT = "CREDIT"
    VND = "VND"


@dataclass(frozen=True)
class Wallet:
    credit: CreditUnits
    vnd: VndUnits


@dataclass(frozen=True)
class Account:
    username: str
    first_name: str
    wallet: Wallet


@dataclass(frozen=True)
class Product:
    id: str
    sku: str
    name: str
    description: str
    price_credit: CreditUnits
    price_vnd: VndUnits
    payment_mode: PaymentMode
    delivery_type: str
    stock: int
    in_stock: bool


class OutcomeCode(StrEnum):
    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    BAD_GATEWAY = "bad_gateway"
    TIMEOUT = "timeout"
    MALFORMED_JSON = "malformed_json"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True)
class ReadSuccess:
    value: Account | Product | tuple[Product, ...]
    status: Literal["success"] = field(default="success", init=False)


@dataclass(frozen=True)
class ReadFailure:
    code: OutcomeCode
    status_code: int | None = None
    retryable: Literal[False] = field(default=False, init=False)
    status: Literal["error"] = field(default="error", init=False)


type ReadOutcome = ReadSuccess | ReadFailure

_ACCOUNT_FIELDS = {"username", "firstName", "wallet"}
_WALLET_FIELDS = {"credit", "vnd"}
_PRODUCT_FIELDS = {
    "id",
    "sku",
    "name",
    "description",
    "priceCredit",
    "priceVnd",
    "paymentMode",
    "deliveryType",
    "stock",
    "inStock",
}


def decode_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise UnsupportedSchemaError("body", "malformed JSON") from None


def _exact_object(value: object, fields: set[str], location: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise UnsupportedSchemaError(location, "expected exactly the documented fields")
    return value


def _text(value: object, location: str) -> str:
    if type(value) is not str:
        raise UnsupportedSchemaError(location, "expected a string")
    return value


def _non_negative_int(value: object, location: str) -> int:
    if type(value) is not int or value < 0:
        raise UnsupportedSchemaError(location, "expected a non-negative integer")
    return value


def parse_account(value: object) -> Account:
    data = _exact_object(value, _ACCOUNT_FIELDS, "account")
    wallet = _exact_object(data["wallet"], _WALLET_FIELDS, "wallet")
    return Account(
        username=_text(data["username"], "username"),
        first_name=_text(data["firstName"], "firstName"),
        wallet=Wallet(
            credit=CreditUnits(_non_negative_int(wallet["credit"], "wallet.credit")),
            vnd=VndUnits(_non_negative_int(wallet["vnd"], "wallet.vnd")),
        ),
    )


def parse_product(value: object) -> Product:
    data = _exact_object(value, _PRODUCT_FIELDS, "product")
    mode = data["paymentMode"]
    if type(mode) is not str or mode not in PaymentMode:
        raise UnsupportedSchemaError("paymentMode", "expected CREDIT or VND")
    in_stock = data["inStock"]
    if type(in_stock) is not bool:
        raise UnsupportedSchemaError("inStock", "expected a boolean")
    return Product(
        id=_text(data["id"], "id"),
        sku=_text(data["sku"], "sku"),
        name=_text(data["name"], "name"),
        description=_text(data["description"], "description"),
        price_credit=CreditUnits(_non_negative_int(data["priceCredit"], "priceCredit")),
        price_vnd=VndUnits(_non_negative_int(data["priceVnd"], "priceVnd")),
        payment_mode=PaymentMode(mode),
        delivery_type=_text(data["deliveryType"], "deliveryType"),
        stock=_non_negative_int(data["stock"], "stock"),
        in_stock=in_stock,
    )


def parse_products(value: object) -> tuple[Product, ...]:
    if type(value) is not list:
        raise UnsupportedSchemaError("products", "unknown or ambiguous response envelope")
    return tuple(parse_product(item) for item in value)
