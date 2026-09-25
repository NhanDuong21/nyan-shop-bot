"""Offline-only VietShare order contract with an injected transport."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from nyan_shop_bot.suppliers.vietshare.adapter import parse_retry_after
from nyan_shop_bot.suppliers.vietshare.models import (
    SensitiveHeaders,
    VietShareCredentials,
    VietShareRequest,
    VietShareResponse,
)
from nyan_shop_bot.suppliers.vietshare.write_journal import JournalConflict, SqliteWriteJournal

_KEY = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")
_ORDER_CODE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_PATH = "/v1/orders"


class WriteContractError(ValueError):
    """Validation failure that never includes request or response material."""


class WriteState(StrEnum):
    COMPLETED = "COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"
    UNKNOWN = "UNKNOWN"
    MISMATCH = "IDEMPOTENCY_MISMATCH"
    REPLAYED_REQUEST = "REPLAYED_REQUEST"
    REJECTED = "REJECTED"


@dataclass(frozen=True, repr=False)
class OrderPurchase:
    product_id: int
    quantity: int
    max_unit_price: int
    currency: str = "VND"
    supplier_emails: tuple[str, ...] = field(default=(), repr=False)
    coupon_code: str | None = field(default=None, repr=False)
    flash_sale_id: int | None = None

    def __post_init__(self) -> None:
        if (
            type(self.product_id) is not int
            or self.product_id <= 0
            or type(self.quantity) is not int
            or not 1 <= self.quantity <= 100
            or type(self.max_unit_price) is not int
            or self.max_unit_price <= 0
            or type(self.currency) is not str
            or self.currency not in {"VND", "USD"}
        ):
            raise WriteContractError("Invalid documented order fields")
        if (
            type(self.supplier_emails) is not tuple
            or self.supplier_emails
            and (
                len(self.supplier_emails) != self.quantity
                or any(type(email) is not str or not email for email in self.supplier_emails)
            )
        ):
            raise WriteContractError("Invalid supplier email count")
        if self.coupon_code is not None and (
            type(self.coupon_code) is not str or not 1 <= len(self.coupon_code) <= 64
        ):
            raise WriteContractError("Invalid coupon code")
        if self.flash_sale_id is not None and (
            type(self.flash_sale_id) is not int or self.flash_sale_id <= 0
        ):
            raise WriteContractError("Invalid flash sale identifier")

    def raw_body(self) -> bytes:
        body: dict[str, object] = {
            "product_id": self.product_id,
            "quantity": self.quantity,
            "max_unit_price": self.max_unit_price,
            "currency": self.currency,
        }
        if self.supplier_emails:
            body["supplier_emails"] = self.supplier_emails
        if self.coupon_code is not None:
            body["coupon_code"] = self.coupon_code
        if self.flash_sale_id is not None:
            body["flash_sale_id"] = self.flash_sale_id
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def __repr__(self) -> str:
        return "OrderPurchase(<redacted>)"


@dataclass(frozen=True, repr=False)
class DeliveredAccounts:
    """Explicitly accessed secret material; never rendered by repr/str."""

    values: tuple[str, ...] = field(repr=False)

    def __repr__(self) -> str:
        return "DeliveredAccounts(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True, repr=False)
class CompletedOrder:
    order_code: str
    product_id: int
    quantity: int
    wallet_currency: str
    supplier_reported_total: int
    accounts: DeliveredAccounts = field(repr=False)
    supplier_total_currency: str = "UNSPECIFIED_BY_SUPPLIER_DOCUMENTATION"

    def __repr__(self) -> str:
        return "CompletedOrder(status=completed, order=<redacted>, delivery=<redacted>)"


@dataclass(frozen=True, repr=False)
class WriteOutcome:
    state: WriteState
    order: CompletedOrder | None = field(default=None, repr=False)
    retry_after_seconds: float | None = None
    error_code: str | None = None

    def __repr__(self) -> str:
        return f"WriteOutcome(state={self.state.value}, details=<redacted>)"


class FakeOnlyTransport(Protocol):
    """The adapter has no socket implementation and no runtime registration."""

    async def send(
        self, request: VietShareRequest, *, timeout_seconds: float
    ) -> VietShareResponse: ...


def _integer(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise WriteContractError("Invalid documented integer field")
    return value


def parse_order_response(raw_body: bytes, *, key: str, purchase: OrderPurchase) -> CompletedOrder:
    """Accept only the documented completed order envelope and delivery shape."""
    try:
        document = json.loads(raw_body)
        if type(document) is not dict or document.get("success") is not True:
            raise WriteContractError("Invalid completed order envelope")
        order = document.get("order")
        if (
            type(order) is not dict
            or order.get("status") != "completed"
            or order.get("channel") != "api"
        ):
            raise WriteContractError("Invalid documented order status")
        code = order.get("order_code")
        product = order.get("product")
        accounts = order.get("accounts")
        unit_prices = order.get("unit_prices")
        breakdown = order.get("price_breakdown")
        if (
            type(code) is not str
            or _ORDER_CODE.fullmatch(code) is None
            or type(product) is not dict
            or _integer(product.get("id"), positive=True) != purchase.product_id
            or type(product.get("name")) is not str
            or order.get("idempotency_key") != key
            or _integer(order.get("quantity"), positive=True) != purchase.quantity
            or type(accounts) is not list
            or len(accounts) != purchase.quantity
            or any(type(account) is not str or not account for account in accounts)
            or type(unit_prices) is not list
            or len(unit_prices) != purchase.quantity
            or type(breakdown) is not list
        ):
            raise WriteContractError("Invalid documented order fields")
        for price in unit_prices:
            _integer(price)
        unit_price = order.get("unit_price")
        if unit_price is not None:
            _integer(unit_price)
        for tier in breakdown:
            if type(tier) is not dict:
                raise WriteContractError("Invalid documented price breakdown")
            _integer(tier.get("quantity"), positive=True)
            _integer(tier.get("unit_price"))
            _integer(tier.get("subtotal"))
        total = _integer(order.get("total_amount"))
        _integer(order.get("discount_amount"))
        for date_name in ("created_at", "delivered_at"):
            if type(order.get(date_name)) is not str or not order[date_name]:
                raise WriteContractError("Invalid documented order time")
            parsed_date = datetime.fromisoformat(order[date_name])
            if parsed_date.tzinfo is None:
                raise WriteContractError("Order time must include a timezone")
        return CompletedOrder(
            order_code=code,
            product_id=purchase.product_id,
            quantity=purchase.quantity,
            wallet_currency=purchase.currency,
            supplier_reported_total=total,
            accounts=DeliveredAccounts(tuple(accounts)),
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        raise WriteContractError("Invalid documented order response") from None


def _error_code(raw_body: bytes) -> str | None:
    try:
        document = json.loads(raw_body)
        detail = document.get("detail") if type(document) is dict else None
        code = detail.get("code") if type(detail) is dict else None
        return code if type(code) is str and re.fullmatch(r"[A-Z_]{1,64}", code) else None
    except (TypeError, ValueError, UnicodeDecodeError):
        return None


def _retry_after(headers: Mapping[str, str], now: int) -> float | None:
    value = next((v for k, v in headers.items() if k.casefold() == "retry-after"), None)
    return parse_retry_after(value, now=now)


class VietShareOfflineWriteAdapter:
    """Journal-backed conformance adapter; caller must inject transport and journal."""

    def __init__(
        self,
        *,
        credentials: VietShareCredentials,
        transport: FakeOnlyTransport,
        journal: SqliteWriteJournal,
        clock: Callable[[], int],
        nonce_source: Callable[[], str],
        timeout_seconds: float = 5,
    ) -> None:
        self._credentials = credentials
        self._transport = transport
        self._journal = journal
        self._clock = clock
        self._nonce_source = nonce_source
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        return "VietShareOfflineWriteAdapter(<redacted>)"

    def prepare(self, operation_id: str, key: str, purchase: OrderPurchase) -> None:
        if type(key) is not str or _KEY.fullmatch(key) is None:
            raise WriteContractError("Invalid Idempotency-Key")
        self._journal.prepare(operation_id, key, purchase.raw_body())

    def _request(
        self,
        *,
        operation_id: str,
        method: str,
        path: str,
        raw_body: bytes,
        now: int,
        key: str | None = None,
    ) -> tuple[VietShareRequest, int]:
        nonce = self._nonce_source()
        if (
            type(now) is not int
            or now < 0
            or type(nonce) is not str
            or not 12 <= len(nonce) <= 128
            or "\r" in nonce
            or "\n" in nonce
        ):
            raise WriteContractError("Invalid or reused signing timestamp/nonce")
        try:
            self._journal.reserve_auth(operation_id, timestamp=now, nonce=nonce)
        except JournalConflict:
            raise WriteContractError("Signing timestamp or nonce was previously used") from None
        canonical = f"{now}|{nonce}|{method}|{path}|{hashlib.sha256(raw_body).hexdigest()}"
        signature = hmac.new(
            self._credentials.secret_bytes, canonical.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        headers = {
            "X-Shop-API-ID": self._credentials.api_id,
            "X-Timestamp": str(now),
            "X-Nonce": nonce,
            "X-Signature": signature,
        }
        if key is not None:
            headers["Idempotency-Key"] = key
            headers["Content-Type"] = "application/json"
        request = VietShareRequest(
            method=method,
            url=f"https://token.vietshare.site{path}",
            path_with_query=path,
            headers=SensitiveHeaders(headers),
            body=raw_body,
        )
        return request, now

    async def submit(self, operation_id: str) -> WriteOutcome:
        now = self._clock()
        if type(now) is not int or now < 0:
            raise WriteContractError("Invalid signing timestamp")
        record = self._journal.begin_attempt(operation_id, now=now)
        if record is None:
            previous = self._journal.get(operation_id)
            if previous is None:
                raise WriteContractError("Order must be durably prepared before dispatch")
            if previous.state == "COMPLETED":
                return WriteOutcome(WriteState.COMPLETED)
            if previous.state == "MISMATCH":
                return WriteOutcome(WriteState.MISMATCH)
            if previous.state == "REJECTED":
                return WriteOutcome(WriteState.REJECTED)
            wait = (
                max(0.0, previous.retry_not_before - now)
                if previous.retry_not_before is not None
                else None
            )
            return WriteOutcome(WriteState.IN_PROGRESS, retry_after_seconds=wait)
        try:
            request, now = self._request(
                operation_id=operation_id,
                method="POST",
                path=_PATH,
                raw_body=record.body,
                now=now,
                key=record.idempotency_key,
            )
        except WriteContractError:
            self._journal.finish_attempt(operation_id, "UNKNOWN")
            raise
        try:
            response = await self._transport.send(request, timeout_seconds=self._timeout)
        except Exception:
            self._journal.finish_attempt(operation_id, "UNKNOWN")
            return WriteOutcome(WriteState.UNKNOWN)
        code = _error_code(response.body)
        has_retry_after = any(name.casefold() == "retry-after" for name in response.headers)
        received_at = (
            self._clock()
            if response.status_code == 202 or code == "REQUEST_IN_PROGRESS" or has_retry_after
            else now
        )
        retry_after = _retry_after(response.headers, received_at)
        if response.status_code == 202:
            self._journal.finish_attempt(
                operation_id, "IN_PROGRESS", retry_not_before=received_at + (retry_after or 1.0)
            )
            return WriteOutcome(WriteState.IN_PROGRESS, retry_after_seconds=retry_after)
        if code == "REQUEST_IN_PROGRESS":
            self._journal.finish_attempt(
                operation_id, "IN_PROGRESS", retry_not_before=received_at + (retry_after or 1.0)
            )
            return WriteOutcome(WriteState.IN_PROGRESS, retry_after_seconds=retry_after)
        if code == "REPLAYED_REQUEST":
            self._journal.finish_attempt(operation_id, "REPLAYED_REQUEST")
            return WriteOutcome(WriteState.REPLAYED_REQUEST, error_code=code)
        if code == "IDEMPOTENCY_MISMATCH":
            self._journal.finish_attempt(operation_id, "MISMATCH")
            return WriteOutcome(WriteState.MISMATCH, error_code=code)
        if response.status_code == 200:
            try:
                purchase_data = json.loads(record.body)
                purchase = OrderPurchase(
                    product_id=purchase_data["product_id"],
                    quantity=purchase_data["quantity"],
                    max_unit_price=purchase_data["max_unit_price"],
                    currency=purchase_data["currency"],
                    supplier_emails=tuple(purchase_data.get("supplier_emails", ())),
                    coupon_code=purchase_data.get("coupon_code"),
                    flash_sale_id=purchase_data.get("flash_sale_id"),
                )
                order = parse_order_response(
                    response.body, key=record.idempotency_key, purchase=purchase
                )
            except (WriteContractError, TypeError, ValueError, KeyError):
                self._journal.finish_attempt(operation_id, "UNKNOWN")
                return WriteOutcome(WriteState.UNKNOWN)
            self._journal.finish_attempt(operation_id, "COMPLETED", order.order_code)
            return WriteOutcome(WriteState.COMPLETED, order=order)
        if response.status_code in {400, 401, 402, 403, 404, 409, 422} and code is not None:
            self._journal.finish_attempt(operation_id, "REJECTED")
            return WriteOutcome(WriteState.REJECTED, error_code=code)
        self._journal.finish_attempt(operation_id, "UNKNOWN")
        return WriteOutcome(WriteState.UNKNOWN, retry_after_seconds=retry_after, error_code=code)

    async def get_delivered_order(self, operation_id: str) -> WriteOutcome:
        """Read back a known completed order; this also uses only injected transport."""
        record = self._journal.get(operation_id)
        if record is None or record.state != "COMPLETED" or record.order_code is None:
            raise WriteContractError("A completed order code is required for delivery lookup")
        if _ORDER_CODE.fullmatch(record.order_code) is None:
            raise WriteContractError("Invalid stored order code")
        now = self._clock()
        request, now = self._request(
            operation_id=operation_id,
            method="GET",
            path=f"{_PATH}/{record.order_code}",
            raw_body=b"",
            now=now,
        )
        try:
            response = await self._transport.send(request, timeout_seconds=self._timeout)
        except Exception:
            return WriteOutcome(WriteState.UNKNOWN)
        if response.status_code != 200:
            return WriteOutcome(
                WriteState.UNKNOWN, retry_after_seconds=_retry_after(response.headers, now)
            )
        try:
            purchase_data = json.loads(record.body)
            purchase = OrderPurchase(
                product_id=purchase_data["product_id"],
                quantity=purchase_data["quantity"],
                max_unit_price=purchase_data["max_unit_price"],
                currency=purchase_data["currency"],
                supplier_emails=tuple(purchase_data.get("supplier_emails", ())),
                coupon_code=purchase_data.get("coupon_code"),
                flash_sale_id=purchase_data.get("flash_sale_id"),
            )
            order = parse_order_response(
                response.body, key=record.idempotency_key, purchase=purchase
            )
            if order.order_code != record.order_code:
                return WriteOutcome(WriteState.UNKNOWN)
        except (WriteContractError, TypeError, ValueError, KeyError):
            return WriteOutcome(WriteState.UNKNOWN)
        return WriteOutcome(WriteState.COMPLETED, order=order)
