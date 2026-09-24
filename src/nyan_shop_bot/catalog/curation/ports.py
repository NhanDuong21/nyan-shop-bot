"""Persistence boundary for the local curation document."""

from typing import Protocol

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationDocument,
    CatalogCurationListing,
)


class CatalogCurationRevisionConflict(RuntimeError):
    """The submitted revision no longer matches the persisted document."""


class CatalogCurationRepositoryUnavailable(RuntimeError):
    """No durable local curation repository is available."""


class CatalogCurationRepository(Protocol):
    async def load(self) -> CatalogCurationDocument: ...

    async def save(
        self,
        *,
        expected_revision: int,
        listings: tuple[CatalogCurationListing, ...],
    ) -> CatalogCurationDocument: ...
