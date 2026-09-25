"""Offline-only KhoMMO order requests; no idempotency or success schema is assumed."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from nyan_shop_bot.suppliers.khommo.adapter import PRODUCTION_BASE_URL
from nyan_shop_bot.suppliers.khommo.models import (
    KhoMmoResponse,
    KhoMmoToken,
    SensitiveHeaders,
)


class OrderContractError(ValueError):
    """A redaction-safe validation or journal error."""


class UnknownOrderState(StrEnum):
    UNKNOWN_RECONCILING = "UNKNOWN_RECONCILING"
    NOT_DISPATCHED = "NOT_DISPATCHED"


@dataclass(frozen=True, repr=False)
class CreateOrder:
    product_id: str
    quantity: int
    payment_mode: str

    def __post_init__(self) -> None:
        if (
            type(self.product_id) is not str
            or not self.product_id
            or "\r" in self.product_id
            or "\n" in self.product_id
            or type(self.quantity) is not int
            or self.quantity <= 0
            or type(self.payment_mode) is not str
            or self.payment_mode not in {"CREDIT", "VND"}
        ):
            raise OrderContractError("Invalid documented KhoMMO order fields")

    def raw_body(self) -> bytes:
        return json.dumps(
            {
                "productId": self.product_id,
                "quantity": self.quantity,
                "paymentMode": self.payment_mode,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def __repr__(self) -> str:
        return "CreateOrder(<redacted>)"


@dataclass(frozen=True, repr=False)
class OfflineOrderRequest:
    method: str
    url: str = field(repr=False)
    headers: SensitiveHeaders = field(repr=False)
    body: bytes = field(default=b"", repr=False)

    def __repr__(self) -> str:
        return f"OfflineOrderRequest(method={self.method!r}, contents=<redacted>)"


@dataclass(frozen=True)
class OrderObservation:
    state: UnknownOrderState
    http_status: int | None = None


class InjectedOrderTransport(Protocol):
    async def send(
        self, request: OfflineOrderRequest, *, timeout_seconds: float
    ) -> KhoMmoResponse: ...


class OfflineOrderJournal:
    """A durable one-dispatch proof for offline tests, not a live write capability."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS khommo_offline_orders (
                    operation_id TEXT PRIMARY KEY,
                    body BLOB NOT NULL,
                    state TEXT NOT NULL,
                    http_status INTEGER
                )"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path, timeout=5, isolation_level=None)) as db:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db

    def prepare(self, operation_id: str, body: bytes) -> None:
        if type(operation_id) is not str or not operation_id or type(body) is not bytes:
            raise OrderContractError("Invalid offline order identity")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM khommo_offline_orders WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is not None:
                if row[0] != body:
                    raise OrderContractError("Operation already has different order bytes")
                return
            db.execute(
                "INSERT INTO khommo_offline_orders VALUES (?, ?, 'PREPARED', NULL)",
                (operation_id, body),
            )

    def dispatch_once(self, operation_id: str) -> bytes | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                "UPDATE khommo_offline_orders SET state='DISPATCHED' "
                "WHERE operation_id=? AND state='PREPARED'",
                (operation_id,),
            )
            if updated.rowcount != 1:
                return None
            row = db.execute(
                "SELECT body FROM khommo_offline_orders WHERE operation_id=?", (operation_id,)
            ).fetchone()
            assert row is not None
            return bytes(row[0])

    def observe(self, operation_id: str, http_status: int | None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE khommo_offline_orders SET state='UNKNOWN_RECONCILING', http_status=? "
                "WHERE operation_id=? AND state='DISPATCHED'",
                (http_status, operation_id),
            )

    def state(self, operation_id: str) -> OrderObservation:
        with self._connect() as db:
            row = db.execute(
                "SELECT state, http_status FROM khommo_offline_orders WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        if row is None or row[0] == "PREPARED":
            return OrderObservation(UnknownOrderState.NOT_DISPATCHED)
        return OrderObservation(UnknownOrderState.UNKNOWN_RECONCILING, row[1])


class KhoMmoOfflineOrderAdapter:
    """Create once with fake transport; status GET requires a known order number."""

    def __init__(
        self,
        *,
        token: KhoMmoToken,
        transport: InjectedOrderTransport,
        journal: OfflineOrderJournal,
        timeout_seconds: float = 5,
    ) -> None:
        if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
            raise OrderContractError("Invalid timeout")
        self._token = token
        self._transport = transport
        self._journal = journal
        self._timeout = float(timeout_seconds)

    def __repr__(self) -> str:
        return "KhoMmoOfflineOrderAdapter(<redacted>)"

    def prepare(self, operation_id: str, order: CreateOrder) -> None:
        self._journal.prepare(operation_id, order.raw_body())

    def _request(self, method: str, path: str, body: bytes = b"") -> OfflineOrderRequest:
        headers = {"Authorization": f"Bearer {self._token.value}"}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        return OfflineOrderRequest(
            method=method,
            url=PRODUCTION_BASE_URL + path,
            headers=SensitiveHeaders(headers),
            body=body,
        )

    async def create_once(self, operation_id: str) -> OrderObservation:
        body = self._journal.dispatch_once(operation_id)
        if body is None:
            return self._journal.state(operation_id)
        try:
            response = await self._transport.send(
                self._request("POST", "/orders", body), timeout_seconds=self._timeout
            )
        except Exception:
            self._journal.observe(operation_id, None)
            return OrderObservation(UnknownOrderState.UNKNOWN_RECONCILING)
        self._journal.observe(operation_id, response.status_code)
        # The official page does not define the create response schema. Even a
        # 2xx cannot be projected as delivered, and 502 is not a safe rejection.
        return OrderObservation(UnknownOrderState.UNKNOWN_RECONCILING, response.status_code)

    async def get_known_order_status(self, order_no: str) -> OrderObservation:
        """GET only a known order number; no lost-response search is inferred."""
        if (
            type(order_no) is not str
            or not order_no
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", order_no) is None
        ):
            raise OrderContractError("A path-safe known order number is required")
        try:
            response = await self._transport.send(
                self._request("GET", "/orders/" + quote(order_no, safe="")),
                timeout_seconds=self._timeout,
            )
        except Exception:
            return OrderObservation(UnknownOrderState.UNKNOWN_RECONCILING)
        # No documented response fields/status enum/delivery shape are available.
        # Do not expose an opaque body containing possible account material.
        return OrderObservation(UnknownOrderState.UNKNOWN_RECONCILING, response.status_code)
