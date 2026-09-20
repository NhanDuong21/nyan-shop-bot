"""Deterministic synthetic supplier data; no partner data or credentials."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from nyan_shop_bot.catalog.models import (
    ApprovedMappingApproval,
    Capability,
    CapabilityStatus,
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogDetailResponse,
    CatalogError,
    CatalogErrorCode,
    CatalogFreshness,
    CatalogProduct,
    CatalogResponse,
    CatalogState,
    CatalogVariant,
    FreshnessStatus,
    Money,
    SupplierCapabilities,
    SupplierMapping,
    SupplierProductIdentity,
    SupplierVariantIdentity,
)


class FakeCatalogScenario(StrEnum):
    """Named deterministic outcomes used by the app and generated UI fixtures."""

    FRESH = "fresh"
    STALE = "stale"
    EMPTY = "empty"
    ERROR = "error"


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 20, hour, minute, tzinfo=UTC)


def _mapping(product_id: str, variant_id: str) -> SupplierMapping:
    return SupplierMapping(
        supplier_product=SupplierProductIdentity(
            supplier_id="fake-supplier",
            supplier_product_id=product_id,
        ),
        supplier_variant=SupplierVariantIdentity(
            supplier_id="fake-supplier",
            supplier_variant_id=variant_id,
        ),
        approval=ApprovedMappingApproval(
            status="approved",
            approved_by_admin_id="fixture-admin",
            approved_at=_utc(0),
        ),
    )


_PRODUCTS = (
    CatalogProduct(
        id="learning-pass",
        name="Synthetic learning pass",
        description="Fixture-only access used to test the normalized catalog.",
        price=Money(amount_minor=49_000, currency="VND", unit="minor"),
        available_quantity=12,
        variants=(
            CatalogVariant(
                id="learning-pass-30d",
                name="30 days",
                mapping=_mapping("supplier-learning-pass", "supplier-learning-pass-30d"),
                price=Money(amount_minor=49_000, currency="VND", unit="minor"),
                available_quantity=12,
            ),
        ),
    ),
    CatalogProduct(
        id="design-seat",
        name="Synthetic design seat",
        description="Synthetic inventory that does not represent a real supplier offer.",
        price=Money(amount_minor=25_000, currency="VND", unit="minor"),
        available_quantity=5,
        variants=(
            CatalogVariant(
                id="design-seat-7d",
                name="7 days",
                mapping=_mapping("supplier-design-seat", "supplier-design-seat-7d"),
                price=Money(amount_minor=25_000, currency="VND", unit="minor"),
                available_quantity=5,
            ),
        ),
    ),
    CatalogProduct(
        id="toolkit",
        name="Synthetic toolkit",
        description="Out-of-stock fixture that cannot be purchased or delivered.",
        price=Money(amount_minor=79_000, currency="VND", unit="minor"),
        available_quantity=0,
        variants=(
            CatalogVariant(
                id="toolkit-1m",
                name="1 month",
                mapping=_mapping("supplier-toolkit", "supplier-toolkit-1m"),
                price=Money(amount_minor=79_000, currency="VND", unit="minor"),
                available_quantity=0,
            ),
        ),
    ),
)

_FRESHNESS = CatalogFreshness(
    status=FreshnessStatus.FRESH,
    observed_at=_utc(0),
    evaluated_at=_utc(0, 5),
    max_age_seconds=900,
)
_STALE_FRESHNESS = CatalogFreshness(
    status=FreshnessStatus.STALE,
    observed_at=_utc(0),
    evaluated_at=_utc(1),
    max_age_seconds=900,
)
_REFRESH_ERROR = CatalogError(
    code=CatalogErrorCode.SOURCE_UNAVAILABLE,
    message="The deterministic refresh failed; cached mock data is shown.",
    retryable=True,
)
_SOURCE_ERROR = CatalogError(
    code=CatalogErrorCode.SOURCE_UNAVAILABLE,
    message="The deterministic mock catalog is unavailable.",
    retryable=True,
)


def fake_catalog_scenarios() -> dict[FakeCatalogScenario, CatalogResponse]:
    """Build all UI states from the same validated public response model."""
    return {
        FakeCatalogScenario.FRESH: CatalogResponse(
            mode="mock",
            state=CatalogState.FRESH,
            freshness=_FRESHNESS,
            items=_PRODUCTS,
            error=None,
        ),
        FakeCatalogScenario.STALE: CatalogResponse(
            mode="mock",
            state=CatalogState.STALE,
            freshness=_STALE_FRESHNESS,
            items=_PRODUCTS,
            error=_REFRESH_ERROR,
        ),
        FakeCatalogScenario.EMPTY: CatalogResponse(
            mode="mock",
            state=CatalogState.EMPTY,
            freshness=_FRESHNESS,
            items=(),
            error=None,
        ),
        FakeCatalogScenario.ERROR: CatalogResponse(
            mode="mock",
            state=CatalogState.ERROR,
            freshness=None,
            items=(),
            error=_SOURCE_ERROR,
        ),
    }


class FakeCatalogReader:
    """Read-only fake supplier with fixed identities, prices, stock, and time."""

    capabilities = SupplierCapabilities(
        catalog_read=Capability(status=CapabilityStatus.ENABLED, reason=None),
        catalog_detail=Capability(status=CapabilityStatus.ENABLED, reason=None),
        purchase=Capability(
            status=CapabilityStatus.DISABLED,
            reason="Purchases are disabled in mock-only mode.",
        ),
        payment=Capability(
            status=CapabilityStatus.DISABLED,
            reason="Payments are disabled in mock-only mode.",
        ),
        top_up=Capability(
            status=CapabilityStatus.DISABLED,
            reason="Top-ups are disabled in mock-only mode.",
        ),
        refund=Capability(
            status=CapabilityStatus.DISABLED,
            reason="Refunds are disabled in mock-only mode.",
        ),
        delivery=Capability(
            status=CapabilityStatus.DISABLED,
            reason="Delivery is disabled in mock-only mode.",
        ),
    )

    def __init__(self, scenario: FakeCatalogScenario = FakeCatalogScenario.FRESH) -> None:
        self._scenario = scenario

    async def read_catalog(self) -> CatalogResponse:
        """Return one immutable validated scenario without clock or network input."""
        return fake_catalog_scenarios()[self._scenario]

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        """Look up only the normalized id; names never participate in mapping."""
        product = next((item for item in _PRODUCTS if item.id == product_id), None)
        if product is None:
            return CatalogDetailNotFound(state="not_found", product_id=product_id)
        return CatalogDetailFound(state="found", item=product)


# Preserve the Phase 0 import name while making the fake-supplier role explicit.
MockCatalogReader = FakeCatalogReader
