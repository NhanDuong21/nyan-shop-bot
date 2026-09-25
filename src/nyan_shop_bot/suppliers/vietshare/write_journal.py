"""Durable, offline VietShare send journal. No network or runtime wiring."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path


class JournalConflict(ValueError):
    """An operation or idempotency key was reused for different bytes."""


@dataclass(frozen=True, repr=False)
class PreparedWrite:
    operation_id: str
    idempotency_key: str = field(repr=False)
    body: bytes = field(repr=False)
    state: str
    order_code: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return f"PreparedWrite(state={self.state!r}, contents=<redacted>)"


class SqliteWriteJournal:
    """Commit the exact key and bytes before dispatch; intended for offline conformance.

    Production integration will require an equivalent PostgreSQL transaction and
    process ownership. A DISPATCHING record is never retried automatically after
    a crash: an operator must first mark its outcome UNKNOWN.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        with self._connect() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS vietshare_writes (
                    operation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    body BLOB NOT NULL,
                    state TEXT NOT NULL,
                    order_code TEXT
                )"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path, timeout=5, isolation_level=None)) as db:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db

    @staticmethod
    def _record(row: tuple[str, str, bytes, str, str | None]) -> PreparedWrite:
        return PreparedWrite(*row)

    def prepare(self, operation_id: str, idempotency_key: str, body: bytes) -> PreparedWrite:
        if not operation_id or not idempotency_key or type(body) is not bytes:
            raise JournalConflict("Invalid write journal input")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT operation_id, idempotency_key, body, state, order_code "
                "FROM vietshare_writes WHERE operation_id=? OR idempotency_key=?",
                (operation_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                record = self._record(existing)
                if (record.operation_id, record.idempotency_key, record.body) != (
                    operation_id,
                    idempotency_key,
                    body,
                ):
                    raise JournalConflict(
                        "Operation or idempotency key conflicts with stored bytes"
                    )
                return record
            db.execute(
                "INSERT INTO vietshare_writes VALUES (?, ?, ?, 'PREPARED', NULL)",
                (operation_id, idempotency_key, body),
            )
            return PreparedWrite(operation_id, idempotency_key, body, "PREPARED")

    def get(self, operation_id: str) -> PreparedWrite | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT operation_id, idempotency_key, body, state, order_code "
                "FROM vietshare_writes WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def begin_attempt(self, operation_id: str) -> PreparedWrite | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                "UPDATE vietshare_writes SET state='DISPATCHING' WHERE operation_id=? "
                "AND state IN ('PREPARED', 'UNKNOWN', 'IN_PROGRESS')",
                (operation_id,),
            )
            if updated.rowcount != 1:
                return None
            row = db.execute(
                "SELECT operation_id, idempotency_key, body, state, order_code "
                "FROM vietshare_writes WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            assert row is not None
            return self._record(row)

    def finish_attempt(self, operation_id: str, state: str, order_code: str | None = None) -> None:
        if state not in {"UNKNOWN", "IN_PROGRESS", "REJECTED", "MISMATCH", "COMPLETED"}:
            raise JournalConflict("Invalid write state")
        with self._connect() as db:
            updated = db.execute(
                "UPDATE vietshare_writes SET state=?, order_code=? "
                "WHERE operation_id=? AND state='DISPATCHING'",
                (state, order_code, operation_id),
            )
            if updated.rowcount != 1:
                raise JournalConflict("Write attempt has no active dispatch")

    def mark_interrupted_unknown(self, operation_id: str) -> None:
        """Operator-only recovery after confirming the old dispatcher has stopped."""
        with self._connect() as db:
            updated = db.execute(
                "UPDATE vietshare_writes SET state='UNKNOWN' "
                "WHERE operation_id=? AND state='DISPATCHING'",
                (operation_id,),
            )
            if updated.rowcount != 1:
                raise JournalConflict("No interrupted dispatch to reconcile")
