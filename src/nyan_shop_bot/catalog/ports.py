"""Read-only supplier boundary for normalized catalog data."""

from typing import Protocol

from nyan_shop_bot.catalog.models import (
    CatalogDetailResponse,
    CatalogResponse,
    SupplierCapabilities,
)


class CatalogReader(Protocol):
    """The complete supplier-facing boundary authorized for NSB-010."""

    @property
    def capabilities(self) -> SupplierCapabilities: ...

    async def read_catalog(self) -> CatalogResponse: ...

    async def get_product(self, product_id: str) -> CatalogDetailResponse: ...
