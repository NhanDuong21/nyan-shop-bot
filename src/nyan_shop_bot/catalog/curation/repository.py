"""PostgreSQL and test repositories for catalog curation."""

from __future__ import annotations

import asyncio
from copy import deepcopy

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationDocument,
    CatalogCurationListing,
)
from nyan_shop_bot.catalog.curation.ports import (
    CatalogCurationRepositoryUnavailable,
    CatalogCurationRevisionConflict,
)

_DOCUMENT_ID = "seller-catalog"
_metadata = sa.MetaData()
_documents = sa.Table(
    "catalog_curation_documents",
    _metadata,
    sa.Column("id", sa.String(length=32), primary_key=True),
    sa.Column("revision", sa.BigInteger(), nullable=False),
    sa.Column("payload", JSONB(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


class PostgresCatalogCurationRepository:
    """Atomically replace one versioned JSONB document."""

    def __init__(self, bind: AsyncEngine | AsyncConnection) -> None:
        self._bind = bind

    async def load(self) -> CatalogCurationDocument:
        statement = sa.select(_documents.c.revision, _documents.c.payload).where(
            _documents.c.id == _DOCUMENT_ID
        )
        try:
            if isinstance(self._bind, AsyncConnection):
                row = (await self._bind.execute(statement)).mappings().one_or_none()
            else:
                async with self._bind.connect() as connection:
                    row = (await connection.execute(statement)).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise CatalogCurationRepositoryUnavailable(
                "catalog curation database read failed"
            ) from exc
        if row is None:
            return CatalogCurationDocument(revision=0, listings=())
        payload = row["payload"]
        if not isinstance(payload, dict):
            raise CatalogCurationRepositoryUnavailable("persisted curation payload is invalid")
        try:
            return CatalogCurationDocument.model_validate(
                {"revision": row["revision"], "listings": payload.get("listings")}
            )
        except ValidationError as exc:
            raise CatalogCurationRepositoryUnavailable(
                "persisted curation payload is invalid"
            ) from exc

    async def save(
        self,
        *,
        expected_revision: int,
        listings: tuple[CatalogCurationListing, ...],
    ) -> CatalogCurationDocument:
        next_revision = expected_revision + 1
        payload: dict[str, object] = {
            "listings": [listing.model_dump(mode="json") for listing in listings]
        }
        try:
            if isinstance(self._bind, AsyncConnection):
                result = await self._execute_save(
                    self._bind,
                    expected_revision=expected_revision,
                    next_revision=next_revision,
                    payload=payload,
                )
            else:
                async with self._bind.begin() as connection:
                    result = await self._execute_save(
                        connection,
                        expected_revision=expected_revision,
                        next_revision=next_revision,
                        payload=payload,
                    )
        except SQLAlchemyError as exc:
            raise CatalogCurationRepositoryUnavailable(
                "catalog curation database write failed"
            ) from exc
        if result.rowcount != 1:
            raise CatalogCurationRevisionConflict("catalog curation revision changed")
        return CatalogCurationDocument(revision=next_revision, listings=listings)

    @staticmethod
    async def _execute_save(
        connection: AsyncConnection,
        *,
        expected_revision: int,
        next_revision: int,
        payload: dict[str, object],
    ) -> sa.engine.CursorResult[object]:
        now = sa.func.now()
        if expected_revision == 0:
            statement = (
                postgres_insert(_documents)
                .values(
                    id=_DOCUMENT_ID,
                    revision=next_revision,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[_documents.c.id])
            )
            return await connection.execute(statement)
        update_statement = (
            sa.update(_documents)
            .where(
                _documents.c.id == _DOCUMENT_ID,
                _documents.c.revision == expected_revision,
            )
            .values(revision=next_revision, payload=payload, updated_at=now)
        )
        return await connection.execute(update_statement)


class InMemoryCatalogCurationRepository:
    """Deterministic optimistic repository used by focused API tests."""

    def __init__(self, document: CatalogCurationDocument | None = None) -> None:
        self._document = document or CatalogCurationDocument(revision=0, listings=())
        self._lock = asyncio.Lock()

    async def load(self) -> CatalogCurationDocument:
        return self._document.model_copy(deep=True)

    async def save(
        self,
        *,
        expected_revision: int,
        listings: tuple[CatalogCurationListing, ...],
    ) -> CatalogCurationDocument:
        async with self._lock:
            if self._document.revision != expected_revision:
                raise CatalogCurationRevisionConflict("catalog curation revision changed")
            self._document = CatalogCurationDocument(
                revision=expected_revision + 1,
                listings=deepcopy(listings),
            )
            return self._document.model_copy(deep=True)


class UnavailableCatalogCurationRepository:
    """Fail-closed repository for tests injecting only a readiness probe."""

    async def load(self) -> CatalogCurationDocument:
        raise CatalogCurationRepositoryUnavailable("catalog curation database is unavailable")

    async def save(
        self,
        *,
        expected_revision: int,
        listings: tuple[CatalogCurationListing, ...],
    ) -> CatalogCurationDocument:
        del expected_revision, listings
        raise CatalogCurationRepositoryUnavailable("catalog curation database is unavailable")
