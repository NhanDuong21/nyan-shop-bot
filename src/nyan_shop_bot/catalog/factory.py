"""Construct the configured read-only catalog for API and bot runtimes."""

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable

from nyan_shop_bot.catalog.mock import MockCatalogReader
from nyan_shop_bot.catalog.models import CatalogSupplier
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.catalog.registry import CatalogRegistry
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


def _build_khommo_reader(settings: Settings) -> tuple[CatalogReader, AsyncCloser]:
    token = settings.khommo_api_token
    if token is None:
        raise RuntimeError("Validated KhoMMO read-only settings are missing a token")
    transport = KhoMmoHttpTransport()
    adapter = KhoMmoReadAdapter(
        token=KhoMmoToken(token.get_secret_value()),
        transport=transport,
    )
    return KhoMmoCatalogReader(adapter), transport.aclose


def _build_vietshare_reader(settings: Settings) -> tuple[CatalogReader, AsyncCloser]:
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


def _combined_closer(closers: tuple[AsyncCloser, ...]) -> AsyncCloser | None:
    if not closers:
        return None

    async def close_all() -> None:
        await asyncio.gather(*(closer() for closer in closers))

    return close_all


def build_catalog_registry(settings: Settings) -> tuple[CatalogRegistry, AsyncCloser | None]:
    """Build every reader authorized by the validated runtime mode."""
    if settings.supplier_mode == "mock":
        return CatalogRegistry({"mock": MockCatalogReader()}), None

    readers: dict[CatalogSupplier, CatalogReader] = {}
    closers: list[AsyncCloser] = []
    if settings.supplier_mode in {"khommo-readonly", "multi-readonly"}:
        readers["khommo"], close_khommo = _build_khommo_reader(settings)
        closers.append(close_khommo)
    if settings.supplier_mode in {"vietshare-readonly", "multi-readonly"}:
        readers["vietshare"], close_vietshare = _build_vietshare_reader(settings)
        closers.append(close_vietshare)

    return CatalogRegistry(readers), _combined_closer(tuple(closers))


def build_catalog_reader(settings: Settings) -> tuple[CatalogReader, AsyncCloser | None]:
    """Build one selected source for backward-compatible single-source callers."""
    registry, close_catalog = build_catalog_registry(settings)
    return registry.resolve(), close_catalog
