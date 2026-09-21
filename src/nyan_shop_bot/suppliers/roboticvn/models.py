"""Strict, redaction-safe response models for the Roboticvn v2 read boundary."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any, Literal, Never
from urllib.parse import parse_qsl, unquote, unquote_plus, urlsplit

from nyan_shop_bot.suppliers.roboticvn.provenance import (
    API_PREFIX,
    GLOBAL_AUTH_HEADER,
)


class RoboticvnConfigurationError(ValueError):
    """A safe configuration error that never includes a rejected value."""


class MalformedJsonError(ValueError):
    """The supplier response was not one unambiguous JSON document."""

    def __init__(self) -> None:
        super().__init__("Malformed Roboticvn JSON response.")


class UnsupportedSchemaError(ValueError):
    """The response does not satisfy the documented projection."""

    def __init__(self, location: str, problem: str) -> None:
        self.location = location
        self.problem = problem
        super().__init__(f"Unsupported Roboticvn schema at {location}: {problem}.")


@dataclass(frozen=True, repr=False)
class RoboticvnApiKey:
    """An API key whose text is never included in its representation."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.value) is not str
            or not self.value
            or any(ord(character) < 32 or ord(character) == 127 for character in self.value)
        ):
            raise RoboticvnConfigurationError(
                "API key must be non-empty text without control characters"
            )

    def __repr__(self) -> str:
        return "RoboticvnApiKey(<redacted>)"

    __str__ = __repr__


class SensitiveHeaders(Mapping[str, str]):
    """An immutable header mapping with a fully redacted representation."""

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


def _request_path_is_authorized(path: str) -> bool:
    static_paths = {
        f"{API_PREFIX}/products",
        f"{API_PREFIX}/wallet/balance",
        f"{API_PREFIX}/wallet/transactions",
    }
    if path in static_paths:
        return True
    detail_prefix = f"{API_PREFIX}/products/"
    if not path.startswith(detail_prefix):
        return False
    segment = path.removeprefix(detail_prefix)
    if not segment or "/" in segment or "\\" in segment:
        return False
    for _ in range(len(segment) + 1):
        try:
            decoded = unquote(segment, errors="strict")
        except UnicodeDecodeError:
            return False
        normalized = unicodedata.normalize("NFKC", decoded)
        if (
            decoded in {".", ".."}
            or normalized in {".", ".."}
            or "/" in decoded
            or "\\" in decoded
            or "/" in normalized
            or "\\" in normalized
            or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in decoded)
        ):
            return False
        if decoded == segment:
            return True
        segment = decoded
    return False


def _request_target_contains_api_key(url: str, api_key: str) -> bool:
    candidate = url
    for _ in range(len(url) + 1):
        if api_key in candidate:
            return True
        try:
            decoded = unquote_plus(candidate, errors="strict")
        except UnicodeDecodeError:
            raise RoboticvnConfigurationError("Roboticvn request target is invalid") from None
        if decoded == candidate:
            return False
        candidate = decoded
    return True


def _validate_request_target(url: str, api_key: str) -> None:
    if type(url) is not str:
        raise RoboticvnConfigurationError("Roboticvn request target is invalid")
    try:
        target = urlsplit(url)
        port = target.port
    except ValueError:
        raise RoboticvnConfigurationError("Roboticvn request target is invalid") from None
    if (
        target.scheme != "https"
        or target.netloc != "api.roboticvn.com"
        or target.hostname != "api.roboticvn.com"
        or port is not None
        or target.username is not None
        or target.password is not None
        or target.fragment
        or not _request_path_is_authorized(target.path)
    ):
        raise RoboticvnConfigurationError("Roboticvn request target is not an authorized read")
    if any(
        name.casefold() == GLOBAL_AUTH_HEADER
        for name, _ in parse_qsl(target.query, keep_blank_values=True)
    ):
        raise RoboticvnConfigurationError("API key must not be placed in the request URL")
    if _request_target_contains_api_key(url, api_key):
        raise RoboticvnConfigurationError("API key must not appear in the request URL")


@dataclass(frozen=True, repr=False)
class RoboticvnRequest:
    """One authenticated request produced by the read-only adapter."""

    method: Literal["GET"]
    url: str = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise RoboticvnConfigurationError("Roboticvn requests must use GET")
        headers = dict(self.headers)
        if set(headers) != {GLOBAL_AUTH_HEADER}:
            raise RoboticvnConfigurationError("API key must be the only request header")
        api_key = RoboticvnApiKey(headers[GLOBAL_AUTH_HEADER])
        _validate_request_target(self.url, api_key.value)
        object.__setattr__(self, "headers", SensitiveHeaders(headers))

    def __repr__(self) -> str:
        return "RoboticvnRequest(method='GET', url=<redacted>, headers=<redacted>)"


@dataclass(frozen=True, repr=False)
class RoboticvnResponse:
    """Raw response bytes whose body and headers stay out of representations."""

    status_code: int
    body: bytes = field(default=b"", repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or type(self.body) is not bytes:
            raise RoboticvnConfigurationError("Roboticvn response must contain a status and bytes")
        object.__setattr__(self, "headers", SensitiveHeaders(self.headers))

    def __repr__(self) -> str:
        return (
            f"RoboticvnResponse(status_code={self.status_code!r}, "
            "body=<redacted>, headers=<redacted>)"
        )


class AbsentValue(Enum):
    """Distinguishes an omitted optional upstream field from a null value."""

    FIELD = "absent"


ABSENT = AbsentValue.FIELD


class MonetaryProjectionGap(StrEnum):
    """Why an upstream numeric value cannot become repository money."""

    UNIT_AND_SCALE_UNDOCUMENTED = "unit_and_scale_undocumented"


@dataclass(frozen=True, repr=False)
class UnsupportedMonetaryProjection:
    """A fail-closed marker that deliberately stores no upstream amount."""

    currency_codes: tuple[str, ...] = field(default=(), repr=False)
    reason: MonetaryProjectionGap = field(
        default=MonetaryProjectionGap.UNIT_AND_SCALE_UNDOCUMENTED,
        init=False,
    )
    status: Literal["unsupported"] = field(default="unsupported", init=False)
    retryable: Literal[False] = field(default=False, init=False)

    def __repr__(self) -> str:
        return (
            "UnsupportedMonetaryProjection("
            "currency_codes=<redacted>, reason='unit_and_scale_undocumented')"
        )


@dataclass(frozen=True, repr=False)
class PaginationMeta:
    count: int
    limit: int
    offset: int

    def __repr__(self) -> str:
        return "PaginationMeta(count=<redacted>, limit=<redacted>, offset=<redacted>)"


@dataclass(frozen=True, repr=False)
class ProductSummary:
    id: str
    title: str

    def __repr__(self) -> str:
        return "ProductSummary(id=<redacted>, title=<redacted>)"


@dataclass(frozen=True, repr=False)
class ProductList:
    data: tuple[ProductSummary, ...]
    meta: PaginationMeta

    def __repr__(self) -> str:
        return f"ProductList(data=<redacted:{len(self.data)}>, meta=<redacted>)"


@dataclass(frozen=True, repr=False)
class ProductVariant:
    id: str
    title: str
    prices: UnsupportedMonetaryProjection
    in_stock: bool
    available_quantity: int
    description: str | None | AbsentValue = ABSENT
    delivery_instructions: str | None | AbsentValue = ABSENT
    reseller_notes: str | None | AbsentValue = ABSENT

    def __repr__(self) -> str:
        return "ProductVariant(<redacted>)"


@dataclass(frozen=True, repr=False)
class Product:
    """Product fields remain optional exactly as declared upstream."""

    id: str | AbsentValue = ABSENT
    title: str | AbsentValue = ABSENT
    description: str | None | AbsentValue = ABSENT
    thumbnail: str | None | AbsentValue = ABSENT
    in_stock: bool | AbsentValue = ABSENT
    variants: tuple[ProductVariant, ...] | AbsentValue = ABSENT

    def __repr__(self) -> str:
        return "Product(<redacted>)"


@dataclass(frozen=True, repr=False)
class WalletBalance:
    monetary_projection: UnsupportedMonetaryProjection

    def __repr__(self) -> str:
        return "WalletBalance(monetary_projection=<unsupported>)"


class WalletTransactionType(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class WalletTransactionReason(StrEnum):
    TOPUP = "topup"
    REFUND = "refund"
    PURCHASE = "purchase"
    ADJUSTMENT = "adjustment"
    OTHER = "other"


@dataclass(frozen=True, repr=False)
class WalletTransaction:
    """Optional transaction metadata with any numeric amount discarded safely."""

    type: WalletTransactionType | AbsentValue = ABSENT
    reason: WalletTransactionReason | AbsentValue = ABSENT
    description: str | AbsentValue = ABSENT
    amount: UnsupportedMonetaryProjection | AbsentValue = ABSENT
    currency_code: str | AbsentValue = ABSENT
    created_at: str | AbsentValue = ABSENT

    def __repr__(self) -> str:
        return "WalletTransaction(<redacted>)"


@dataclass(frozen=True, repr=False)
class WalletTransactionList:
    data: tuple[WalletTransaction, ...]
    meta: PaginationMeta

    def __repr__(self) -> str:
        return f"WalletTransactionList(data=<redacted:{len(self.data)}>, meta=<redacted>)"


type ReadValue = ProductList | Product | WalletBalance | WalletTransactionList


class OutcomeCode(StrEnum):
    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    SUPPLIER_ERROR = "supplier_error"
    TIMEOUT = "timeout"
    MALFORMED_JSON = "malformed_json"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    TRANSPORT_ERROR = "transport_error"
    UNEXPECTED_STATUS = "unexpected_status"


@dataclass(frozen=True, repr=False)
class ReadSuccess:
    value: ReadValue = field(repr=False)
    attempts: Literal[1] = field(default=1, init=False)
    status: Literal["success"] = field(default="success", init=False)

    def __repr__(self) -> str:
        return "ReadSuccess(value=<redacted>, attempts=1)"


@dataclass(frozen=True)
class ReadFailure:
    code: OutcomeCode
    status_code: int | None = None
    attempts: Literal[1] = field(default=1, init=False)
    retryable: Literal[False] = field(default=False, init=False)
    status: Literal["error"] = field(default="error", init=False)


type ReadOutcome = ReadSuccess | ReadFailure


_PRODUCT_SUMMARY_FIELDS = frozenset({"id", "title"})
_PRODUCT_FIELDS = frozenset({"id", "title", "description", "thumbnail", "in_stock", "variants"})
_PRODUCT_VARIANT_FIELDS = frozenset(
    {
        "id",
        "title",
        "description",
        "prices",
        "in_stock",
        "available_quantity",
        "delivery_instructions",
        "reseller_notes",
    }
)
_PRODUCT_VARIANT_REQUIRED = frozenset({"id", "title", "prices", "in_stock", "available_quantity"})
_PAGINATION_REQUIRED = frozenset({"count", "limit", "offset"})
_TRANSACTION_FIELDS = frozenset(
    {"type", "reason", "description", "amount", "currency_code", "created_at"}
)
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")


def _reject_json_constant(_value: str) -> Never:
    raise ValueError("non-finite JSON number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _decode_json(body: bytes) -> Any:
    if type(body) is not bytes:
        raise MalformedJsonError
    try:
        return json.loads(
            body,
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, ValueError, RecursionError, MemoryError):
        raise MalformedJsonError from None


def _object(value: object, location: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise UnsupportedSchemaError(location, "expected an object")
    return value


def _array(value: object, location: str) -> list[Any]:
    if type(value) is not list:
        raise UnsupportedSchemaError(location, "expected an array")
    return value


def _required(data: Mapping[str, Any], fields: frozenset[str], location: str) -> None:
    if not fields.issubset(data):
        raise UnsupportedSchemaError(location, "missing a documented required field")


def _no_extensions(data: Mapping[str, Any], fields: frozenset[str], location: str) -> None:
    if not set(data).issubset(fields):
        raise UnsupportedSchemaError(location, "contains an undocumented additional property")


def _text(value: object, location: str) -> str:
    if type(value) is not str:
        raise UnsupportedSchemaError(location, "expected a string")
    return value


def _nullable_text(value: object, location: str) -> str | None:
    if value is None:
        return None
    return _text(value, location)


def _integer(value: object, location: str) -> int:
    if type(value) is not int:
        raise UnsupportedSchemaError(location, "expected an integer")
    return value


def _boolean(value: object, location: str) -> bool:
    if type(value) is not bool:
        raise UnsupportedSchemaError(location, "expected a boolean")
    return value


def _number(value: object, location: str) -> None:
    if type(value) is int:
        return
    if type(value) is Decimal and value.is_finite():
        return
    raise UnsupportedSchemaError(location, "expected a finite JSON number")


def _unsupported_currency_object(value: object, location: str) -> UnsupportedMonetaryProjection:
    data = _object(value, location)
    for amount in data.values():
        _number(amount, f"{location}.*")
    return UnsupportedMonetaryProjection(currency_codes=tuple(data))


def _pagination(value: object, location: str) -> PaginationMeta:
    data = _object(value, location)
    _required(data, _PAGINATION_REQUIRED, location)
    return PaginationMeta(
        count=_integer(data["count"], f"{location}.count"),
        limit=_integer(data["limit"], f"{location}.limit"),
        offset=_integer(data["offset"], f"{location}.offset"),
    )


def _product_summary(value: object, location: str) -> ProductSummary:
    data = _object(value, location)
    _required(data, _PRODUCT_SUMMARY_FIELDS, location)
    _no_extensions(data, _PRODUCT_SUMMARY_FIELDS, location)
    return ProductSummary(
        id=_text(data["id"], f"{location}.id"),
        title=_text(data["title"], f"{location}.title"),
    )


def _product_variant(value: object, location: str) -> ProductVariant:
    data = _object(value, location)
    _required(data, _PRODUCT_VARIANT_REQUIRED, location)
    _no_extensions(data, _PRODUCT_VARIANT_FIELDS, location)

    description: str | None | AbsentValue = ABSENT
    if "description" in data:
        description = _nullable_text(data["description"], f"{location}.description")
    delivery_instructions: str | None | AbsentValue = ABSENT
    if "delivery_instructions" in data:
        delivery_instructions = _nullable_text(
            data["delivery_instructions"], f"{location}.delivery_instructions"
        )
    reseller_notes: str | None | AbsentValue = ABSENT
    if "reseller_notes" in data:
        reseller_notes = _nullable_text(data["reseller_notes"], f"{location}.reseller_notes")

    return ProductVariant(
        id=_text(data["id"], f"{location}.id"),
        title=_text(data["title"], f"{location}.title"),
        prices=_unsupported_currency_object(data["prices"], f"{location}.prices"),
        in_stock=_boolean(data["in_stock"], f"{location}.in_stock"),
        available_quantity=_integer(data["available_quantity"], f"{location}.available_quantity"),
        description=description,
        delivery_instructions=delivery_instructions,
        reseller_notes=reseller_notes,
    )


def _product(value: object) -> Product:
    data = _object(value, "data")
    _no_extensions(data, _PRODUCT_FIELDS, "data")

    product_id: str | AbsentValue = ABSENT
    if "id" in data:
        product_id = _text(data["id"], "data.id")
    title: str | AbsentValue = ABSENT
    if "title" in data:
        title = _text(data["title"], "data.title")
    description: str | None | AbsentValue = ABSENT
    if "description" in data:
        description = _nullable_text(data["description"], "data.description")
    thumbnail: str | None | AbsentValue = ABSENT
    if "thumbnail" in data:
        thumbnail = _nullable_text(data["thumbnail"], "data.thumbnail")
    in_stock: bool | AbsentValue = ABSENT
    if "in_stock" in data:
        in_stock = _boolean(data["in_stock"], "data.in_stock")
    variants: tuple[ProductVariant, ...] | AbsentValue = ABSENT
    if "variants" in data:
        items = _array(data["variants"], "data.variants")
        variants = tuple(
            _product_variant(item, f"data.variants[{index}]") for index, item in enumerate(items)
        )

    return Product(
        id=product_id,
        title=title,
        description=description,
        thumbnail=thumbnail,
        in_stock=in_stock,
        variants=variants,
    )


def _enum_text[T: StrEnum](value: object, enum_type: type[T], location: str, expected: str) -> T:
    text = _text(value, location)
    try:
        return enum_type(text)
    except ValueError:
        raise UnsupportedSchemaError(location, expected) from None


def _date_time(value: object, location: str) -> str:
    text = _text(value, location)
    if not _RFC3339.fullmatch(text):
        raise UnsupportedSchemaError(location, "expected an RFC 3339 date-time")
    if int(text[11:13]) > 23:
        raise UnsupportedSchemaError(location, "expected an RFC 3339 date-time")
    normalized = text[:10] + "T" + text[11:]
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise UnsupportedSchemaError(location, "expected an RFC 3339 date-time") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UnsupportedSchemaError(location, "expected an RFC 3339 date-time")
    return text


def _wallet_transaction(value: object, location: str) -> WalletTransaction:
    data = _object(value, location)
    _no_extensions(data, _TRANSACTION_FIELDS, location)

    transaction_type: WalletTransactionType | AbsentValue = ABSENT
    if "type" in data:
        transaction_type = _enum_text(
            data["type"],
            WalletTransactionType,
            f"{location}.type",
            "expected credit or debit",
        )
    reason: WalletTransactionReason | AbsentValue = ABSENT
    if "reason" in data:
        reason = _enum_text(
            data["reason"],
            WalletTransactionReason,
            f"{location}.reason",
            "expected a documented transaction reason",
        )
    description: str | AbsentValue = ABSENT
    if "description" in data:
        description = _text(data["description"], f"{location}.description")
    currency_code: str | AbsentValue = ABSENT
    if "currency_code" in data:
        currency_code = _text(data["currency_code"], f"{location}.currency_code")
    amount: UnsupportedMonetaryProjection | AbsentValue = ABSENT
    if "amount" in data:
        _number(data["amount"], f"{location}.amount")
        currencies = () if currency_code is ABSENT else (currency_code,)
        amount = UnsupportedMonetaryProjection(currency_codes=currencies)
    created_at: str | AbsentValue = ABSENT
    if "created_at" in data:
        created_at = _date_time(data["created_at"], f"{location}.created_at")

    return WalletTransaction(
        type=transaction_type,
        reason=reason,
        description=description,
        amount=amount,
        currency_code=currency_code,
        created_at=created_at,
    )


def parse_product_list(body: bytes) -> ProductList:
    envelope = _object(_decode_json(body), "response")
    _required(envelope, frozenset({"data", "meta"}), "response")
    items = _array(envelope["data"], "data")
    return ProductList(
        data=tuple(_product_summary(item, f"data[{index}]") for index, item in enumerate(items)),
        meta=_pagination(envelope["meta"], "meta"),
    )


def parse_product_detail(body: bytes) -> Product:
    envelope = _object(_decode_json(body), "response")
    _required(envelope, frozenset({"data"}), "response")
    return _product(envelope["data"])


def parse_wallet_balance(body: bytes) -> WalletBalance:
    envelope = _object(_decode_json(body), "response")
    _required(envelope, frozenset({"data"}), "response")
    return WalletBalance(monetary_projection=_unsupported_currency_object(envelope["data"], "data"))


def parse_wallet_transactions(body: bytes) -> WalletTransactionList:
    envelope = _object(_decode_json(body), "response")
    _required(envelope, frozenset({"data", "meta"}), "response")
    items = _array(envelope["data"], "data")
    return WalletTransactionList(
        data=tuple(_wallet_transaction(item, f"data[{index}]") for index, item in enumerate(items)),
        meta=_pagination(envelope["meta"], "meta"),
    )
