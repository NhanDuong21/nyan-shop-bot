"""FastAPI application factory for mock or explicit local live-read catalog mode."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, status
from fastapi.middleware.cors import CORSMiddleware

from nyan_shop_bot.catalog.mock import MockCatalogReader
from nyan_shop_bot.catalog.models import (
    CatalogDetailResponse,
    CatalogResponse,
    SupplierCapabilities,
)
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.config import Settings, get_settings
from nyan_shop_bot.database import DatabaseProbe, PostgresDatabase
from nyan_shop_bot.suppliers.khommo import (
    KhoMmoCatalogReader,
    KhoMmoCatalogSourceUnavailable,
    KhoMmoHttpTransport,
    KhoMmoReadAdapter,
    KhoMmoToken,
)

AsyncCloser = Callable[[], Awaitable[None]]


def build_catalog_reader(settings: Settings) -> tuple[CatalogReader, AsyncCloser | None]:
    """Build only the catalog source selected by validated runtime settings."""
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


def create_app(
    *,
    settings: Settings | None = None,
    catalog: CatalogReader | None = None,
    database: DatabaseProbe | None = None,
) -> FastAPI:
    """Create an app with replaceable read-only dependencies."""
    runtime_settings = settings or get_settings()
    if catalog is None:
        catalog_reader, close_catalog = build_catalog_reader(runtime_settings)
    else:
        catalog_reader, close_catalog = catalog, None
    database_probe = database or PostgresDatabase(runtime_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            try:
                if close_catalog is not None:
                    await close_catalog()
            finally:
                await database_probe.close()

    application = FastAPI(
        title="Nyan Shop Bot API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )

    @application.get("/healthz", tags=["system"])
    async def health() -> dict[str, str | bool]:
        return {
            "status": "ok",
            "supplier_mode": runtime_settings.supplier_mode,
            "payment_mode": runtime_settings.payment_mode,
            "allow_real_purchases": runtime_settings.allow_real_purchases,
            "read_only": True,
        }

    @application.get("/readyz", tags=["system"])
    async def readiness() -> dict[str, str]:
        try:
            ready = await database_probe.ping()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            ) from exc
        if not ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            )
        return {"status": "ready"}

    @application.get("/api/v1/catalog", response_model=CatalogResponse, tags=["catalog"])
    async def list_catalog() -> CatalogResponse:
        return await catalog_reader.read_catalog()

    @application.get(
        "/api/v1/catalog/{product_id}",
        response_model=CatalogDetailResponse,
        tags=["catalog"],
    )
    async def catalog_detail(
        product_id: Annotated[str, Path(min_length=1, pattern=r".*\S.*")],
    ) -> CatalogDetailResponse:
        try:
            return await catalog_reader.get_product(product_id)
        except KhoMmoCatalogSourceUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="catalog source unavailable",
            ) from exc

    @application.get(
        "/api/v1/capabilities",
        response_model=SupplierCapabilities,
        tags=["catalog"],
    )
    async def capabilities() -> SupplierCapabilities:
        return catalog_reader.capabilities

    return application


app = create_app()
