"""Local-only FastAPI routes for catalog curation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationSaveRequest,
    CatalogCurationWorkspace,
)
from nyan_shop_bot.catalog.curation.ports import (
    CatalogCurationRepositoryUnavailable,
    CatalogCurationRevisionConflict,
)
from nyan_shop_bot.catalog.curation.service import (
    CatalogCurationService,
    UnknownCatalogOffer,
)
from nyan_shop_bot.config import Settings, is_loopback_host

_ALLOWED_ADMIN_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})


def build_catalog_curation_router(
    *,
    settings: Settings,
    service: CatalogCurationService,
) -> APIRouter:
    """Build routes with immutable local-only safety dependencies."""
    router = APIRouter(prefix="/api/v1/admin/catalog-curation", tags=["admin"])

    async def require_local_admin(request: Request) -> None:
        client = request.client
        if (
            settings.app_env != "local"
            or not is_loopback_host(settings.app_host)
            or client is None
            or not is_loopback_host(client.host)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="catalog curation is available only from local loopback",
            )

    async def require_local_json_write(
        request: Request,
        _: None = Depends(require_local_admin),
    ) -> None:
        origin = request.headers.get("origin")
        content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0]
        if origin not in _ALLOWED_ADMIN_ORIGINS or content_type.lower() != "application/json":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="catalog curation write requires the local admin origin and JSON",
            )

    @router.get(
        "",
        response_model=CatalogCurationWorkspace,
        dependencies=[Depends(require_local_admin)],
    )
    async def get_workspace() -> CatalogCurationWorkspace:
        try:
            return await service.get_workspace()
        except CatalogCurationRepositoryUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="catalog curation database is unavailable",
            ) from exc

    @router.put(
        "",
        response_model=CatalogCurationWorkspace,
        dependencies=[Depends(require_local_json_write)],
    )
    async def save_workspace(
        body: CatalogCurationSaveRequest,
    ) -> CatalogCurationWorkspace:
        try:
            return await service.save_workspace(body)
        except CatalogCurationRevisionConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="catalog curation revision changed; reload before saving",
            ) from exc
        except UnknownCatalogOffer as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except CatalogCurationRepositoryUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="catalog curation database is unavailable",
            ) from exc

    return router
