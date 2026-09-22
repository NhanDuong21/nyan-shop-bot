"""Focused validation tests for the normalized catalog contract."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nyan_shop_bot.catalog.models import (
    ApprovedMappingApproval,
    Capability,
    CapabilityStatus,
    CatalogDetailUnsupported,
    CatalogError,
    CatalogErrorCode,
    CatalogFreshness,
    CatalogResponse,
    CatalogState,
    FreshnessStatus,
    Money,
    PendingMappingApproval,
    SupplierCapabilities,
    SupplierMapping,
    SupplierProductIdentity,
    SupplierVariantIdentity,
)


def approved_mapping() -> SupplierMapping:
    return SupplierMapping(
        supplier_product=SupplierProductIdentity(
            supplier_id="supplier-a",
            supplier_product_id="product-7",
        ),
        supplier_variant=SupplierVariantIdentity(
            supplier_id="supplier-a",
            supplier_variant_id="variant-11",
        ),
        approval=ApprovedMappingApproval(
            status="approved",
            approved_by_admin_id="admin-1",
            approved_at=datetime(2026, 9, 20, tzinfo=UTC),
        ),
    )


@pytest.mark.parametrize("amount", [1.5, "100", True])
def test_money_rejects_non_integer_minor_units(amount: object) -> None:
    with pytest.raises(ValidationError):
        Money.model_validate({"amount_minor": amount, "currency": "VND", "unit": "minor"})


@pytest.mark.parametrize(
    "value",
    [
        {"amount_minor": 100, "unit": "minor"},
        {"amount_minor": 100, "currency": "VND"},
        {"amount_minor": 100, "currency": "vnd", "unit": "minor"},
        {"amount_minor": 100, "currency": "VND", "unit": "major"},
    ],
)
def test_money_requires_explicit_valid_currency_and_unit(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Money.model_validate(value)


def test_money_adds_only_matching_currency_and_unit() -> None:
    left = Money(amount_minor=100, currency="VND", unit="minor")
    right = Money(amount_minor=25, currency="VND", unit="minor")

    assert left.add(right) == Money(amount_minor=125, currency="VND", unit="minor")
    with pytest.raises(ValueError, match="currency and unit"):
        left.add(Money(amount_minor=25, currency="USD", unit="minor"))


def test_mapping_requires_explicit_admin_approval_evidence() -> None:
    mapping = approved_mapping()

    assert mapping.is_approved
    assert mapping.supplier_product.supplier_product_id == "product-7"
    assert mapping.supplier_variant.supplier_variant_id == "variant-11"
    with pytest.raises(ValidationError):
        SupplierMapping.model_validate(
            {
                "supplier_product": {
                    "supplier_id": "supplier-a",
                    "supplier_product_id": "product-7",
                },
                "supplier_variant": {
                    "supplier_id": "supplier-a",
                    "supplier_variant_id": "variant-11",
                },
                "approval": {"status": "approved"},
            }
        )


def test_pending_mapping_is_never_implicitly_approved() -> None:
    mapping = SupplierMapping(
        supplier_product=SupplierProductIdentity(
            supplier_id="supplier-a",
            supplier_product_id="product-7",
        ),
        supplier_variant=SupplierVariantIdentity(
            supplier_id="supplier-a",
            supplier_variant_id="variant-11",
        ),
        approval=PendingMappingApproval(status="pending"),
    )

    assert not mapping.is_approved


def test_mapping_does_not_cross_supplier_identity_boundaries() -> None:
    with pytest.raises(ValidationError, match="share a supplier"):
        SupplierMapping(
            supplier_product=SupplierProductIdentity(
                supplier_id="supplier-a",
                supplier_product_id="same-display-name",
            ),
            supplier_variant=SupplierVariantIdentity(
                supplier_id="supplier-b",
                supplier_variant_id="same-display-name",
            ),
            approval=PendingMappingApproval(status="pending"),
        )


def test_freshness_is_derived_from_timestamps_and_max_age() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        CatalogFreshness(
            status=FreshnessStatus.FRESH,
            observed_at=datetime(2026, 9, 20, tzinfo=UTC),
            evaluated_at=datetime(2026, 9, 20, 1, tzinfo=UTC),
            max_age_seconds=60,
        )


def test_error_state_rejects_items_or_freshness() -> None:
    with pytest.raises(ValidationError, match="only error evidence"):
        CatalogResponse(
            mode="mock",
            state=CatalogState.ERROR,
            freshness=CatalogFreshness(
                status=FreshnessStatus.FRESH,
                observed_at=datetime(2026, 9, 20, tzinfo=UTC),
                evaluated_at=datetime(2026, 9, 20, tzinfo=UTC),
                max_age_seconds=60,
            ),
            items=(),
            error=CatalogError(
                code=CatalogErrorCode.SOURCE_UNAVAILABLE,
                message="Synthetic error.",
                retryable=True,
            ),
        )


def test_catalog_source_and_mode_cannot_disagree() -> None:
    with pytest.raises(ValidationError, match="supplier and mode"):
        CatalogResponse(
            supplier="khommo",
            mode="mock",
            state=CatalogState.ERROR,
            freshness=None,
            items=(),
            error=CatalogError(
                code=CatalogErrorCode.SOURCE_UNAVAILABLE,
                message="Synthetic error.",
                retryable=False,
            ),
        )


def test_partial_catalog_requires_positive_omission_evidence_and_populated_state() -> None:
    error = CatalogError(
        code=CatalogErrorCode.SOURCE_UNAVAILABLE,
        message="Synthetic error.",
        retryable=False,
    )
    with pytest.raises(ValidationError, match="omitted item evidence"):
        CatalogResponse(
            mode="mock",
            state=CatalogState.ERROR,
            freshness=None,
            items=(),
            error=error,
            partial=True,
            omitted_count=0,
        )
    with pytest.raises(ValidationError, match="populated catalog"):
        CatalogResponse(
            mode="mock",
            state=CatalogState.ERROR,
            freshness=None,
            items=(),
            error=error,
            partial=True,
            omitted_count=1,
        )


def test_write_capabilities_cannot_be_enabled() -> None:
    enabled = Capability(status=CapabilityStatus.ENABLED, reason=None)
    disabled = Capability(status=CapabilityStatus.DISABLED, reason="Mock-only boundary.")

    with pytest.raises(ValidationError, match="must stay disabled"):
        SupplierCapabilities(
            catalog_read=enabled,
            catalog_detail=enabled,
            purchase=enabled,
            payment=disabled,
            top_up=disabled,
            refund=disabled,
            delivery=disabled,
        )


def test_missing_supplier_detail_can_remain_explicitly_unsupported() -> None:
    enabled = Capability(status=CapabilityStatus.ENABLED, reason=None)
    disabled = Capability(status=CapabilityStatus.DISABLED, reason="Mock-only boundary.")
    unsupported = Capability(
        status=CapabilityStatus.UNSUPPORTED,
        reason="Supplier detail schema has not been verified.",
    )
    capabilities = SupplierCapabilities(
        catalog_read=enabled,
        catalog_detail=unsupported,
        purchase=disabled,
        payment=disabled,
        top_up=disabled,
        refund=disabled,
        delivery=disabled,
    )
    detail = CatalogDetailUnsupported(
        state="unsupported",
        product_id="catalog-product",
        error=CatalogError(
            code=CatalogErrorCode.UNSUPPORTED,
            message="Supplier detail is unsupported.",
            retryable=False,
        ),
    )

    assert capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert capabilities.catalog_detail.status is CapabilityStatus.UNSUPPORTED
    assert detail.state == "unsupported"
