"""FastAPI application factory for the mock-only foundation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from nyan_shop_bot.catalog.mock import MockCatalogReader
from nyan_shop_bot.catalog.models import CatalogResponse, SupplierCapabilities
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.config import Settings, get_settings
from nyan_shop_bot.database import DatabaseProbe, PostgresDatabase


def create_app(
    *,
    settings: Settings | None = None,
    catalog: CatalogReader | None = None,
    database: DatabaseProbe | None = None,
) -> FastAPI:
    """Create an app with replaceable read-only dependencies."""
    runtime_settings = settings or get_settings()
    catalog_reader = catalog or MockCatalogReader()
    database_probe = database or PostgresDatabase(runtime_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
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
        return CatalogResponse(items=await catalog_reader.list_products())

    @application.get(
        "/api/v1/capabilities",
        response_model=SupplierCapabilities,
        tags=["catalog"],
    )
    async def capabilities() -> SupplierCapabilities:
        return catalog_reader.capabilities

    return application


app = create_app()
