"""Dormant, source-specific local runtime for one approved VietShare test.

No application route or bot imports this module. An operator must explicitly
enable the separate environment kill switch and arm the exact database tuple.
"""

from __future__ import annotations

import csv
import ctypes
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from nyan_shop_bot.suppliers.vietshare.models import (
    ProductDetailSuccess,
    SensitiveHeaders,
    VietShareCredentials,
    VietShareRequest,
    VietShareResponse,
)
from nyan_shop_bot.suppliers.vietshare.pg_gate import (
    CappedTestIntent,
    GateOutcome,
    GateState,
    VietSharePgGate,
    _canonical_bytes,
)
from nyan_shop_bot.suppliers.vietshare.secret_delivery import VietShareSecretDeliveryStore
from nyan_shop_bot.suppliers.vietshare.write_orders import (
    OrderPurchase,
    WriteContractError,
    _error_code,
    _retry_after,
    parse_order_response,
)

APPROVED_PRODUCT_ID = 28
APPROVED_QUANTITY = 1
HARD_SPEND_CEILING_VND = 100_000
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_REQUIRED_FIELD_HINTS = (
    "supplier_emails",
    "supplier emails",
    "cung cấp email",
    "cung cap email",
    "nhập email",
    "nhap email",
    "email của bạn",
    "email cua ban",
    "own email",
    "your email",
    "coupon_code",
    "coupon code",
    "mã giảm giá",
    "ma giam gia",
    "flash_sale_id",
    "flash sale",
)


class CappedRuntimeError(ValueError):
    """Redacted local gate error."""


class OperatorIdentity(Protocol):
    def current_id(self) -> str: ...


class ProductDetailReader(Protocol):
    async def get_product(self, product_id: int) -> object: ...


class CappedOrderTransport(Protocol):
    async def send(
        self, request: VietShareRequest, *, timeout_seconds: float
    ) -> VietShareResponse: ...


class LocalOsOperatorIdentity:
    """Bind to the process token's Windows SID or POSIX effective UID."""

    def current_id(self) -> str:
        if os.name != "nt":
            if not hasattr(os, "geteuid"):
                raise CappedRuntimeError("Local operator identity is unavailable")
            return f"unix-uid:{os.geteuid()}"
        try:
            system_dir = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir))
            if not 0 < length < len(system_dir):
                raise ValueError
            whoami = Path(system_dir.value) / "whoami.exe"
            completed = subprocess.run(
                [str(whoami), "/user", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            rows = list(csv.reader(completed.stdout.splitlines()))
            if len(rows) != 1 or len(rows[0]) != 2:
                raise ValueError
            sid = rows[0][1]
            if re.fullmatch(r"S-1-(?:[0-9]+-)*[0-9]+", sid) is None:
                raise ValueError
            return f"win-sid:{sid}"
        except (OSError, ValueError, subprocess.SubprocessError):
            raise CappedRuntimeError("Local operator identity is unavailable") from None


@dataclass(frozen=True, repr=False)
class CappedTestPlan:
    test_id: str
    product_id: int
    quantity: int
    max_unit_price_vnd: int
    absolute_spend_cap_vnd: int
    wallet_id: str = field(repr=False)
    operator_id: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.test_id) is not str
            or not 1 <= len(self.test_id) <= 64
            or _ID.fullmatch(self.test_id) is None
            or type(self.product_id) is not int
            or self.product_id != APPROVED_PRODUCT_ID
            or type(self.quantity) is not int
            or self.quantity != APPROVED_QUANTITY
            or type(self.max_unit_price_vnd) is not int
            or self.max_unit_price_vnd <= 0
            or type(self.absolute_spend_cap_vnd) is not int
            or not self.max_unit_price_vnd <= self.absolute_spend_cap_vnd <= HARD_SPEND_CEILING_VND
            or type(self.wallet_id) is not str
            or _ID.fullmatch(self.wallet_id) is None
            or type(self.operator_id) is not str
            or _ID.fullmatch(self.operator_id) is None
        ):
            raise CappedRuntimeError("Invalid product-28 capped test plan")

    def __repr__(self) -> str:
        return "CappedTestPlan(<redacted>)"


class VietShareCappedTestRuntime:
    """Only explicit local calls can prepare, arm, dispatch, or reconcile."""

    def __init__(
        self,
        *,
        gate: VietSharePgGate,
        delivery_store: VietShareSecretDeliveryStore,
        credentials: VietShareCredentials,
        transport: CappedOrderTransport,
        product_reader: ProductDetailReader,
        operator: OperatorIdentity,
        kill_switch_enabled: bool = False,
        clock: Callable[[], int] | None = None,
        nonce_source: Callable[[], str] | None = None,
        timeout_seconds: float = 5,
    ) -> None:
        if type(kill_switch_enabled) is not bool or type(timeout_seconds) not in (int, float):
            raise CappedRuntimeError("Invalid local runtime configuration")
        if not 0 < timeout_seconds <= 10:
            raise CappedRuntimeError("Invalid local runtime timeout")
        self._gate = gate
        self._delivery_store = delivery_store
        self._credentials = credentials
        self._transport = transport
        self._product_reader = product_reader
        self._operator = operator
        self._kill_switch_enabled = kill_switch_enabled
        self._clock = clock or (lambda: int(time.time()))
        self._nonce_source = nonce_source or (lambda: secrets.token_hex(16))
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        return "VietShareCappedTestRuntime(<redacted>)"

    def _operator_id(self) -> str:
        operator_id = self._operator.current_id()
        if type(operator_id) is not str or _ID.fullmatch(operator_id) is None:
            raise CappedRuntimeError("Authenticated operator identity is invalid")
        return operator_id

    def _require_switch(self) -> None:
        if not self._kill_switch_enabled:
            raise CappedRuntimeError("Local VietShare capped test kill switch is OFF")

    async def prepare(self, plan: CappedTestPlan) -> None:
        if plan.operator_id != self._operator_id():
            raise CappedRuntimeError("Plan operator does not match local authenticated user")
        existing = await self._gate.get(plan.test_id)
        if existing is not None:
            if (
                existing.product_id != plan.product_id
                or existing.quantity != plan.quantity
                or existing.max_unit_price_vnd != plan.max_unit_price_vnd
                or existing.absolute_spend_cap_vnd != plan.absolute_spend_cap_vnd
                or existing.wallet_id != plan.wallet_id
                or existing.operator_id != plan.operator_id
            ):
                raise CappedRuntimeError("Prepared test does not match plan")
            return
        intent = CappedTestIntent(
            test_id=plan.test_id,
            idempotency_key=f"nyan-{secrets.token_hex(16)}",
            purchase=OrderPurchase(plan.product_id, plan.quantity, plan.max_unit_price_vnd, "VND"),
            absolute_spend_cap_vnd=plan.absolute_spend_cap_vnd,
            wallet_id=plan.wallet_id,
            operator_id=plan.operator_id,
        )
        await self._gate.prepare(intent)

    async def arm(self, plan: CappedTestPlan, *, approved_by: str, approval_ref: str) -> None:
        self._require_switch()
        if plan.operator_id != self._operator_id():
            raise CappedRuntimeError("Plan operator does not match local authenticated user")
        await self._gate.arm(
            test_id=plan.test_id,
            product_id=plan.product_id,
            quantity=plan.quantity,
            max_unit_price_vnd=plan.max_unit_price_vnd,
            absolute_spend_cap_vnd=plan.absolute_spend_cap_vnd,
            wallet_id=plan.wallet_id,
            operator_id=plan.operator_id,
            approved_by=approved_by,
            approval_ref=approval_ref,
        )

    async def disarm(self) -> None:
        await self._gate.disarm()

    async def mark_dispatch_lost(self, test_id: str, *, evidence_ref: str) -> None:
        await self._gate.mark_dispatch_lost(
            test_id, operator_id=self._operator_id(), evidence_ref=evidence_ref
        )

    async def mark_reconciling(self, test_id: str, *, evidence_ref: str) -> None:
        await self._gate.mark_reconciling(
            test_id, operator_id=self._operator_id(), evidence_ref=evidence_ref
        )

    async def read_delivery(self, reference: str) -> object:
        return await self._delivery_store.read(reference=reference, operator_id=self._operator_id())

    async def acknowledge_delivery(self, reference: str) -> None:
        await self._delivery_store.acknowledge(reference=reference, operator_id=self._operator_id())

    async def dispatch(self, test_id: str) -> GateOutcome:
        self._require_switch()
        operator_id = self._operator_id()
        record = await self._gate.get(test_id)
        if (
            record is None
            or record.operator_id != operator_id
            or record.product_id != APPROVED_PRODUCT_ID
            or record.quantity != APPROVED_QUANTITY
            or record.absolute_spend_cap_vnd > HARD_SPEND_CEILING_VND
            or record.state not in {GateState.PREPARED, GateState.RECONCILING}
        ):
            raise CappedRuntimeError("Capped test is not eligible for dispatch")
        if record.state is GateState.PREPARED:
            detail = await self._product_reader.get_product(APPROVED_PRODUCT_ID)
            if not isinstance(detail, ProductDetailSuccess):
                raise CappedRuntimeError("Current supplier catalog detail is unavailable")
            product = detail.value
            text = (product.name + " " + product.description).casefold()
            if (
                product.id != APPROVED_PRODUCT_ID
                or product.price_vnd <= 0
                or product.price_vnd > record.max_unit_price_vnd
                or product.stock < APPROVED_QUANTITY
                or product.max_quantity < APPROVED_QUANTITY
                or product.flash_sale_id is not None
                or "VND" not in product.currencies
                or any(hint in text for hint in _REQUIRED_FIELD_HINTS)
            ):
                raise CappedRuntimeError("Supplier product failed current read-only preflight")
        timestamp = self._clock()
        nonce = self._nonce_source()
        claimed = await self._gate.claim(
            test_id=test_id, operator_id=operator_id, timestamp=timestamp, nonce=nonce
        )
        try:
            canonical = _canonical_bytes(timestamp, nonce, claimed.body_sha256)
            signature = hmac.new(
                self._credentials.secret_bytes, canonical, hashlib.sha256
            ).hexdigest()
            request = VietShareRequest(
                method="POST",
                url="https://token.vietshare.site/v1/orders",
                path_with_query="/v1/orders",
                headers=SensitiveHeaders(
                    {
                        "X-Shop-API-ID": self._credentials.api_id,
                        "X-Timestamp": str(timestamp),
                        "X-Nonce": nonce,
                        "X-Signature": signature,
                        "Idempotency-Key": claimed.idempotency_key,
                        "Content-Type": "application/json",
                    }
                ),
                body=claimed.raw_body,
            )
            response = await self._transport.send(request, timeout_seconds=self._timeout)
        except Exception:
            await self._gate.finish(
                test_id, GateState.UNKNOWN, nonce=nonce, error_code="TRANSPORT_ERROR"
            )
            return GateOutcome(GateState.UNKNOWN)
        if not isinstance(response, VietShareResponse):
            await self._gate.finish(
                test_id, GateState.UNKNOWN, nonce=nonce, error_code="INVALID_RESPONSE"
            )
            return GateOutcome(GateState.UNKNOWN)
        code = _error_code(response.body)
        received_at = await self._gate.server_now_seconds()
        retry = _retry_after(response.headers, received_at)
        # Persist only a parsed numeric delay, never an untrusted header value.
        retry = min(retry, 1_000_000_000.0) if retry is not None else None
        retry_header = str(retry) if retry is not None else None
        if response.status_code == 202 or code == "REQUEST_IN_PROGRESS":
            await self._gate.finish(
                test_id,
                GateState.RECONCILING,
                nonce=nonce,
                retry_delay_seconds=retry if retry is not None else 1.0,
                http_status=response.status_code,
                retry_after_header=retry_header,
                error_code=code,
            )
            return GateOutcome(GateState.RECONCILING, retry_after_seconds=retry, error_code=code)
        if code in {"IDEMPOTENCY_MISMATCH", "REPLAYED_REQUEST"}:
            await self._gate.finish(
                test_id,
                GateState.RECONCILING,
                nonce=nonce,
                http_status=response.status_code,
                retry_after_header=retry_header,
                error_code=code,
            )
            return GateOutcome(GateState.RECONCILING, error_code=code)
        if response.status_code == 200:
            try:
                purchase = OrderPurchase(
                    claimed.product_id, claimed.quantity, claimed.max_unit_price_vnd, "VND"
                )
                order = parse_order_response(
                    response.body, key=claimed.idempotency_key, purchase=purchase
                )
            except (WriteContractError, ValueError, TypeError):
                await self._gate.finish(
                    test_id,
                    GateState.UNKNOWN,
                    nonce=nonce,
                    http_status=response.status_code,
                    retry_after_header=retry_header,
                    error_code="INVALID_RESPONSE",
                )
                return GateOutcome(GateState.UNKNOWN)
            try:
                delivery_ref = await self._delivery_store.put(
                    test_id=test_id, order_code=order.order_code, accounts=order.accounts
                )
            except Exception:
                await self._gate.finish(
                    test_id,
                    GateState.RECONCILING,
                    nonce=nonce,
                    http_status=response.status_code,
                    retry_after_header=retry_header,
                    order_code=order.order_code,
                    error_code="SECRET_DELIVERY_UNAVAILABLE",
                )
                return GateOutcome(GateState.RECONCILING, error_code="SECRET_DELIVERY_UNAVAILABLE")
            if order.supplier_reported_total > claimed.absolute_spend_cap_vnd:
                await self._gate.finish(
                    test_id,
                    GateState.RECONCILING,
                    nonce=nonce,
                    http_status=response.status_code,
                    retry_after_header=retry_header,
                    order_code=order.order_code,
                    secret_delivery_ref=delivery_ref,
                    error_code="SPEND_CAP_EXCEEDED",
                )
                return GateOutcome(GateState.RECONCILING, error_code="SPEND_CAP_EXCEEDED")
            await self._gate.finish(
                test_id,
                GateState.SUCCEEDED,
                nonce=nonce,
                http_status=response.status_code,
                retry_after_header=retry_header,
                order_code=order.order_code,
                secret_delivery_ref=delivery_ref,
            )
            return GateOutcome(GateState.SUCCEEDED)
        await self._gate.finish(
            test_id,
            GateState.UNKNOWN,
            nonce=nonce,
            http_status=response.status_code,
            retry_after_header=retry_header,
            error_code=code,
        )
        return GateOutcome(GateState.UNKNOWN, error_code=code)
