"""FastAPI application factory for mock or explicit local live-read catalog mode."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from nyan_shop_bot.catalog.factory import (
    build_catalog_reader as build_catalog_reader,
)
from nyan_shop_bot.catalog.factory import (
    build_catalog_registry,
)
from nyan_shop_bot.catalog.models import (
    CatalogDetailResponse,
    CatalogListResponse,
    CatalogSelection,
    CatalogSourcesResponse,
    CatalogSupplier,
    SupplierCapabilities,
)
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.catalog.registry import (
    CatalogRegistry,
    CatalogSourceSelectionRequired,
    CatalogSourceUnavailable,
)
from nyan_shop_bot.config import Settings, get_settings, is_loopback_host
from nyan_shop_bot.database import DatabaseProbe, PostgresDatabase
from nyan_shop_bot.suppliers.khommo import KhoMmoCatalogSourceUnavailable
from nyan_shop_bot.suppliers.vietshare import VietShareCatalogSourceUnavailable


def create_app(
    *,
    settings: Settings | None = None,
    catalog: CatalogReader | None = None,
    catalogs: CatalogRegistry | None = None,
    database: DatabaseProbe | None = None,
) -> FastAPI:
    """Create an app with replaceable read-only dependencies."""
    runtime_settings = settings or get_settings()
    if catalog is not None and catalogs is not None:
        raise ValueError("inject either one catalog or a catalog registry, not both")
    if catalogs is not None:
        catalog_registry, close_catalog = catalogs, None
    elif catalog is None:
        catalog_registry, close_catalog = build_catalog_registry(runtime_settings)
    else:
        source_by_mode: dict[str, CatalogSupplier] = {
            "mock": "mock",
            "khommo-readonly": "khommo",
            "vietshare-readonly": "vietshare",
        }
        source = source_by_mode.get(runtime_settings.supplier_mode)
        if source is None:
            raise ValueError("multi-readonly tests must inject an explicit catalog registry")
        catalog_registry = CatalogRegistry({source: catalog})
        close_catalog = None
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

    async def require_local_live_read(request: Request) -> None:
        """Reject remote triggers even if a live-read server is accidentally public-bound."""
        if runtime_settings.supplier_mode == "mock":
            return
        client = request.client
        if client is None or not is_loopback_host(client.host):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="live-read catalog is available only from loopback",
            )

    def selected_catalog(source: CatalogSupplier | None) -> CatalogReader:
        try:
            return catalog_registry.resolve(source)
        except CatalogSourceSelectionRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="catalog source selection is required",
            ) from exc
        except CatalogSourceUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="catalog source is not configured",
            ) from exc

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

    @application.get(
        "/api/v1/catalog/sources",
        response_model=CatalogSourcesResponse,
        tags=["catalog"],
        dependencies=[Depends(require_local_live_read)],
    )
    async def catalog_sources() -> CatalogSourcesResponse:
        return catalog_registry.source_response

    @application.get(
        "/api/v1/catalog",
        response_model=CatalogListResponse,
        tags=["catalog"],
        dependencies=[Depends(require_local_live_read)],
    )
    async def list_catalog(
        source: Annotated[CatalogSelection | None, Query()] = None,
    ) -> CatalogListResponse:
        if source == "all":
            try:
                return await catalog_registry.read_aggregate()
            except CatalogSourceUnavailable as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="aggregate catalog is not configured",
                ) from exc
        return await selected_catalog(source).read_catalog()

    @application.get(
        "/api/v1/catalog/{product_id}",
        response_model=CatalogDetailResponse,
        tags=["catalog"],
        dependencies=[Depends(require_local_live_read)],
    )
    async def catalog_detail(
        product_id: Annotated[str, Path(min_length=1, pattern=r".*\S.*")],
        source: Annotated[CatalogSupplier | None, Query()] = None,
    ) -> CatalogDetailResponse:
        try:
            return await selected_catalog(source).get_product(product_id)
        except (KhoMmoCatalogSourceUnavailable, VietShareCatalogSourceUnavailable) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="catalog source unavailable",
            ) from exc

    @application.get(
        "/api/v1/capabilities",
        response_model=SupplierCapabilities,
        tags=["catalog"],
        dependencies=[Depends(require_local_live_read)],
    )
    async def capabilities(
        source: Annotated[CatalogSelection | None, Query()] = None,
    ) -> SupplierCapabilities:
        if source == "all":
            try:
                return catalog_registry.aggregate_capabilities
            except CatalogSourceUnavailable as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="aggregate catalog is not configured",
                ) from exc
        return selected_catalog(source).capabilities

    return application


app = create_app()
