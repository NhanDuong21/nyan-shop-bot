"""Construct the configured read-only catalog for API and bot runtimes."""

import asyncio
import secrets
import time
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
from nyan_shop_bot.suppliers.vietshare import (
    VietShareCatalogReader,
    VietShareCredentials,
    VietShareHttpTransport,
    VietShareReadAdapter,
)

AsyncCloser = Callable[[], Awaitable[None]]


def build_catalog_reader(settings: Settings) -> tuple[CatalogReader, AsyncCloser | None]:
    """Build only the source selected by already-validated runtime settings."""
    if settings.supplier_mode == "mock":
        return MockCatalogReader(), None

    if settings.supplier_mode == "khommo-readonly":
        token = settings.khommo_api_token
        if token is None:
            raise RuntimeError("Validated KhoMMO read-only settings are missing a token")
        transport = KhoMmoHttpTransport()
        adapter = KhoMmoReadAdapter(
            token=KhoMmoToken(token.get_secret_value()),
            transport=transport,
        )
        return KhoMmoCatalogReader(adapter), transport.aclose

    api_id = settings.vietshare_api_id
    api_secret = settings.vietshare_api_secret
    if api_id is None or api_secret is None:
        raise RuntimeError("Validated VietShare read-only settings are missing credentials")
    vietshare_transport = VietShareHttpTransport()
    vietshare_adapter = VietShareReadAdapter(
        credentials=VietShareCredentials(
            api_id=api_id.get_secret_value(),
            api_secret=api_secret.get_secret_value(),
        ),
        transport=vietshare_transport,
        clock=time.time,
        nonce_source=lambda: secrets.token_hex(16),
        retry_sleeper=asyncio.sleep,
        retry_delay_seconds=0.25,
    )
    return VietShareCatalogReader(vietshare_adapter), vietshare_transport.aclose
