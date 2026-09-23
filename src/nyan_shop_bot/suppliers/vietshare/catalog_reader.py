"""Projection from verified VietShare reads into the normalized catalog boundary."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError

from nyan_shop_bot.catalog.models import (
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogDetailResponse,
    CatalogDetailUnsupported,
    CatalogError,
    CatalogErrorCode,
    CatalogFreshness,
    CatalogProduct,
    CatalogResponse,
    CatalogState,
    CatalogVariant,
    FreshnessStatus,
    Money,
    PendingMappingApproval,
    SupplierMapping,
    SupplierProductIdentity,
    SupplierVariantIdentity,
)
from nyan_shop_bot.suppliers.vietshare.adapter import (
    VIETSHARE_CAPABILITIES,
    VietShareReadAdapter,
)
from nyan_shop_bot.suppliers.vietshare.models import (
    ProductDetailNotFound,
    ProductDetailSuccess,
    ProductListError,
    ProductListErrorCode,
    ProductListRateLimited,
    ProductListSuccess,
    ProductListTimeout,
    VietShareConfigurationError,
    VietShareProduct,
    VietShareProductList,
)

Clock = Callable[[], datetime]
type ReadFailure = ProductListError | ProductListRateLimited | ProductListTimeout

_TELEGRAM_CUSTOM_EMOJI_ELEMENT = re.compile(
    r"<tg-emoji\b[^>]*>[^<]*</tg-emoji\s*>",
    flags=re.IGNORECASE,
)


def _strip_telegram_custom_emoji(value: str) -> str:
    """Remove unsupported Telegram Premium custom-emoji elements from display text."""
    return _TELEGRAM_CUSTOM_EMOJI_ELEMENT.sub("", value).strip()


class VietShareCatalogSourceUnavailable(RuntimeError):
    """The live source failed without exposing upstream details."""


class VietShareCatalogReader:
    """A no-cache, read-only catalog reader backed by signed VietShare GET requests."""

    capabilities = VIETSHARE_CAPABILITIES

    def __init__(
        self,
        adapter: VietShareReadAdapter,
        *,
        clock: Clock | None = None,
        max_age_seconds: int = 30,
    ) -> None:
        if type(max_age_seconds) is not int or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be a positive integer")
        self._adapter = adapter
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_age_seconds = max_age_seconds

    @staticmethod
    def _error_for(failure: ReadFailure) -> CatalogError:
        if isinstance(failure, ProductListError):
            if failure.code is ProductListErrorCode.INVALID_RESPONSE:
                return CatalogError(
                    code=CatalogErrorCode.UNSUPPORTED,
                    message="VietShare returned a catalog schema that is not safely supported.",
                    retryable=False,
                )
            retryable = failure.retryable or failure.code in {
                ProductListErrorCode.TRANSPORT_ERROR,
                ProductListErrorCode.RETRY_ERROR,
            }
        else:
            retryable = True
        return CatalogError(
            code=CatalogErrorCode.SOURCE_UNAVAILABLE,
            message="VietShare catalog is temporarily unavailable.",
            retryable=retryable,
        )

    @staticmethod
    def _unsupported_detail(product_id: str) -> CatalogDetailUnsupported:
        return CatalogDetailUnsupported(
            state="unsupported",
            product_id=product_id,
            error=CatalogError(
                code=CatalogErrorCode.UNSUPPORTED,
                message="VietShare product data cannot be projected safely.",
                retryable=False,
            ),
        )

    @staticmethod
    def _project_product(product: VietShareProduct) -> CatalogProduct:
        if product.id <= 0:
            raise ValueError("supplier product identity must be positive")
        identifier = str(product.id)
        price = Money(
            amount_minor=product.price.amount_minor,
            currency="VND",
            unit="minor",
        )
        mapping = SupplierMapping(
            supplier_product=SupplierProductIdentity(
                supplier_id="vietshare",
                supplier_product_id=identifier,
            ),
            supplier_variant=SupplierVariantIdentity(
                supplier_id="vietshare",
                supplier_variant_id=identifier,
            ),
            approval=PendingMappingApproval(status="pending"),
        )
        variant = CatalogVariant(
            id=identifier,
            name=product.name,
            mapping=mapping,
            price=price,
            available_quantity=product.stock,
        )
        return CatalogProduct(
            id=identifier,
            name=product.name,
            description=_strip_telegram_custom_emoji(product.description),
            supplier="vietshare",
            mode="vietshare-readonly",
            read_only=True,
            price=price,
            available_quantity=product.stock,
            variants=(variant,),
        )

    def _freshness(self, observed_at: datetime) -> CatalogFreshness:
        return CatalogFreshness(
            status=FreshnessStatus.FRESH,
            observed_at=observed_at,
            evaluated_at=self._clock(),
            max_age_seconds=self._max_age_seconds,
        )

    async def read_catalog(self) -> CatalogResponse:
        outcome = await self._adapter.list_products()
        if isinstance(outcome, (ProductListError, ProductListRateLimited, ProductListTimeout)):
            return CatalogResponse(
                mode="vietshare-readonly",
                supplier="vietshare",
                read_only=True,
                state=CatalogState.ERROR,
                freshness=None,
                items=(),
                error=self._error_for(outcome),
            )
        if not isinstance(outcome, ProductListSuccess) or not isinstance(
            outcome.value, VietShareProductList
        ):
            return CatalogResponse(
                mode="vietshare-readonly",
                supplier="vietshare",
                read_only=True,
                state=CatalogState.ERROR,
                freshness=None,
                items=(),
                error=CatalogError(
                    code=CatalogErrorCode.UNSUPPORTED,
                    message="VietShare returned an unsupported catalog projection.",
                    retryable=False,
                ),
            )

        try:
            if len({product.id for product in outcome.value.products}) != len(
                outcome.value.products
            ):
                raise ValueError("supplier product identities are not unique")
            items = tuple(self._project_product(product) for product in outcome.value.products)
            observed_at = self._clock()
            freshness = self._freshness(observed_at)
        except (ValidationError, ValueError):
            return CatalogResponse(
                mode="vietshare-readonly",
                supplier="vietshare",
                read_only=True,
                state=CatalogState.ERROR,
                freshness=None,
                items=(),
                error=CatalogError(
                    code=CatalogErrorCode.UNSUPPORTED,
                    message="VietShare product data cannot be projected safely.",
                    retryable=False,
                ),
            )

        return CatalogResponse(
            mode="vietshare-readonly",
            supplier="vietshare",
            read_only=True,
            state=CatalogState.FRESH if items else CatalogState.EMPTY,
            freshness=freshness,
            items=items,
            error=None,
            partial=False,
            omitted_count=0,
        )

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        if not product_id.isascii() or not product_id.isdecimal():
            return CatalogDetailNotFound(state="not_found", product_id=product_id)
        numeric_id = int(product_id)
        if numeric_id <= 0 or str(numeric_id) != product_id:
            return CatalogDetailNotFound(state="not_found", product_id=product_id)

        try:
            outcome = await self._adapter.get_product(numeric_id)
        except VietShareConfigurationError:
            return CatalogDetailNotFound(state="not_found", product_id=product_id)

        if isinstance(outcome, ProductDetailNotFound):
            return CatalogDetailNotFound(state="not_found", product_id=product_id)
        if isinstance(outcome, ProductListError):
            if outcome.code is ProductListErrorCode.INVALID_RESPONSE:
                return self._unsupported_detail(product_id)
            raise VietShareCatalogSourceUnavailable("VietShare product detail is unavailable")
        if isinstance(outcome, (ProductListRateLimited, ProductListTimeout)):
            raise VietShareCatalogSourceUnavailable("VietShare product detail is unavailable")
        if not isinstance(outcome, ProductDetailSuccess):
            return self._unsupported_detail(product_id)

        try:
            item = self._project_product(outcome.value)
        except (ValidationError, ValueError):
            return self._unsupported_detail(product_id)
        if item.id != product_id:
            return self._unsupported_detail(product_id)
        return CatalogDetailFound(state="found", item=item)
