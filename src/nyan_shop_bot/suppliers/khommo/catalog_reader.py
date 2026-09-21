"""Projection from documented KhoMMO reads into the normalized catalog boundary."""

from __future__ import annotations

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
from nyan_shop_bot.suppliers.khommo.adapter import KHOMMO_CAPABILITIES, KhoMmoReadAdapter
from nyan_shop_bot.suppliers.khommo.models import (
    KhoMmoConfigurationError,
    OutcomeCode,
    PaymentMode,
    Product,
    ReadFailure,
    ReadSuccess,
)

Clock = Callable[[], datetime]


class KhoMmoCatalogSourceUnavailable(RuntimeError):
    """The live source failed without exposing upstream details."""


class KhoMmoCatalogReader:
    """A no-cache, read-only catalog reader backed by the KhoMMO GET adapter."""

    capabilities = KHOMMO_CAPABILITIES

    def __init__(
        self,
        adapter: KhoMmoReadAdapter,
        *,
        clock: Clock | None = None,
        max_age_seconds: int = 60,
    ) -> None:
        if type(max_age_seconds) is not int or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be a positive integer")
        self._adapter = adapter
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_age_seconds = max_age_seconds

    @staticmethod
    def _error_for(failure: ReadFailure) -> CatalogError:
        if failure.code in {OutcomeCode.MALFORMED_JSON, OutcomeCode.UNSUPPORTED_SCHEMA}:
            return CatalogError(
                code=CatalogErrorCode.UNSUPPORTED,
                message="KhoMMO returned a catalog schema that is not safely supported.",
                retryable=False,
            )
        if failure.code is OutcomeCode.UNAUTHORIZED:
            return CatalogError(
                code=CatalogErrorCode.SOURCE_UNAVAILABLE,
                message="KhoMMO read authorization was rejected.",
                retryable=False,
            )
        retryable = failure.code in {
            OutcomeCode.TIMEOUT,
            OutcomeCode.BAD_GATEWAY,
            OutcomeCode.TRANSPORT_ERROR,
        }
        return CatalogError(
            code=CatalogErrorCode.SOURCE_UNAVAILABLE,
            message="KhoMMO catalog is temporarily unavailable.",
            retryable=retryable,
        )

    @staticmethod
    def _unsupported_detail(product_id: str) -> CatalogDetailUnsupported:
        return CatalogDetailUnsupported(
            state="unsupported",
            product_id=product_id,
            error=CatalogError(
                code=CatalogErrorCode.UNSUPPORTED,
                message="KhoMMO product data cannot be projected safely.",
                retryable=False,
            ),
        )

    @staticmethod
    def _project_product(product: Product) -> CatalogProduct:
        if product.payment_mode is not PaymentMode.VND:
            raise ValueError("CREDIT catalog prices require a separate normalized unit contract")
        if (
            not product.id.strip()
            or len(product.id) > 128
            or product.id in {".", ".."}
            or "/" in product.id
            or not product.id.isprintable()
        ):
            raise ValueError("supplier product identity is not path safe")
        if product.in_stock != (product.stock > 0):
            raise ValueError("supplier stock fields are inconsistent")

        price = Money(
            amount_minor=product.price_vnd.amount,
            currency="VND",
            unit="minor",
        )
        mapping = SupplierMapping(
            supplier_product=SupplierProductIdentity(
                supplier_id="khommo",
                supplier_product_id=product.id,
            ),
            supplier_variant=SupplierVariantIdentity(
                supplier_id="khommo",
                supplier_variant_id=product.id,
            ),
            approval=PendingMappingApproval(status="pending"),
        )
        variant = CatalogVariant(
            id=product.id,
            name=product.name,
            mapping=mapping,
            price=price,
            available_quantity=product.stock,
        )
        return CatalogProduct(
            id=product.id,
            name=product.name,
            description=product.description,
            supplier="khommo",
            mode="khommo-readonly",
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
        """Read one maximum-sized documented page and reject ambiguous truncation."""
        outcome = await self._adapter.list_products(page=1, limit=500)
        if isinstance(outcome, ReadFailure):
            return CatalogResponse(
                mode="khommo-readonly",
                supplier="khommo",
                read_only=True,
                state=CatalogState.ERROR,
                freshness=None,
                items=(),
                error=self._error_for(outcome),
            )
        if not isinstance(outcome, ReadSuccess) or type(outcome.value) is not tuple:
            return CatalogResponse(
                mode="khommo-readonly",
                supplier="khommo",
                read_only=True,
                state=CatalogState.ERROR,
                freshness=None,
                items=(),
                error=CatalogError(
                    code=CatalogErrorCode.UNSUPPORTED,
                    message="KhoMMO returned an unsupported catalog projection.",
                    retryable=False,
                ),
            )

        products = outcome.value
        if len(products) == 500:
            return CatalogResponse(
                mode="khommo-readonly",
                supplier="khommo",
                read_only=True,
                state=CatalogState.ERROR,
                freshness=None,
                items=(),
                error=CatalogError(
                    code=CatalogErrorCode.UNSUPPORTED,
                    message="KhoMMO pagination is ambiguous at the safe page limit.",
                    retryable=False,
                ),
            )

        try:
            items = tuple(self._project_product(product) for product in products)
            if len({item.id for item in items}) != len(items):
                raise ValueError("supplier product identities are not unique")
            observed_at = self._clock()
            freshness = self._freshness(observed_at)
        except (ValidationError, ValueError):
            return CatalogResponse(
                mode="khommo-readonly",
                supplier="khommo",
                read_only=True,
                state=CatalogState.ERROR,
                freshness=None,
                items=(),
                error=CatalogError(
                    code=CatalogErrorCode.UNSUPPORTED,
                    message="KhoMMO product data cannot be projected safely.",
                    retryable=False,
                ),
            )

        return CatalogResponse(
            mode="khommo-readonly",
            supplier="khommo",
            read_only=True,
            state=CatalogState.FRESH if items else CatalogState.EMPTY,
            freshness=freshness,
            items=items,
            error=None,
        )

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        try:
            outcome = await self._adapter.get_product(product_id)
        except KhoMmoConfigurationError:
            return CatalogDetailNotFound(state="not_found", product_id=product_id)

        if isinstance(outcome, ReadFailure):
            if outcome.code is OutcomeCode.NOT_FOUND:
                return CatalogDetailNotFound(state="not_found", product_id=product_id)
            if outcome.code in {OutcomeCode.MALFORMED_JSON, OutcomeCode.UNSUPPORTED_SCHEMA}:
                return self._unsupported_detail(product_id)
            raise KhoMmoCatalogSourceUnavailable("KhoMMO product detail is unavailable")

        if not isinstance(outcome, ReadSuccess) or not isinstance(outcome.value, Product):
            return self._unsupported_detail(product_id)
        try:
            item = self._project_product(outcome.value)
        except (ValidationError, ValueError):
            return self._unsupported_detail(product_id)
        if item.id != product_id:
            return self._unsupported_detail(product_id)
        return CatalogDetailFound(state="found", item=item)
