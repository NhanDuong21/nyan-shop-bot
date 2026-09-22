"""Construct the configured read-only catalog for API and bot runtimes."""

from collections.abc import Awaitable, Callable

from nyan_shop_bot.catalog.mock import MockCatalogReader
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.config import Settings
from nyan_shop_bot.suppliers.khommo import (
    KhoMmoCatalogReader,
    KhoMmoHttpTransport,
    KhoMmoReadAdapter,
    KhoMmoToken,
)

AsyncCloser = Callable[[], Awaitable[None]]


def build_catalog_reader(settings: Settings) -> tuple[CatalogReader, AsyncCloser | None]:
    """Build only the source selected by already-validated runtime settings."""
    if settings.supplier_mode == "mock":
        return MockCatalogReader(), None

    token = settings.khommo_api_token
    if token is None:
        raise RuntimeError("Validated KhoMMO read-only settings are missing a token")
    transport = KhoMmoHttpTransport()
    adapter = KhoMmoReadAdapter(
        token=KhoMmoToken(token.get_secret_value()),
        transport=transport,
    )
    return KhoMmoCatalogReader(adapter), transport.aclose
