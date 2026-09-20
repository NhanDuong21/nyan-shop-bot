"""Read-only supplier boundary for Phase 0."""

from typing import Protocol

from nyan_shop_bot.catalog.models import CatalogItem, SupplierCapabilities


class CatalogReader(Protocol):
    """The only supplier-facing capability allowed in NSB-001."""

    @property
    def capabilities(self) -> SupplierCapabilities: ...

    async def list_products(self) -> list[CatalogItem]: ...

    async def get_product(self, product_id: str) -> CatalogItem | None: ...
