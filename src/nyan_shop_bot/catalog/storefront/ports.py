"""Read-only boundary shared by FastAPI and Telegram storefront consumers."""

from typing import Protocol

from nyan_shop_bot.catalog.storefront.models import (
    StorefrontCatalogResponse,
    StorefrontDetailResponse,
)


class StorefrontCatalogReader(Protocol):
    async def read_storefront(self) -> StorefrontCatalogResponse: ...

    async def get_storefront_product(self, product_id: str) -> StorefrontDetailResponse: ...
