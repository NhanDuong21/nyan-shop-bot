"""Normalized, read-only catalog contracts.

The models in this module are the source of truth for both FastAPI's OpenAPI
document and the generated UI fixtures. Supplier identifiers are deliberately
opaque: a product or variant is never matched by its display name.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

Identifier = Annotated[StrictStr, Field(min_length=1, pattern=r".*\S.*")]
DisplayText = Annotated[StrictStr, Field(min_length=1, pattern=r".*\S.*")]
CurrencyCode = Annotated[StrictStr, Field(pattern=r"^[A-Z]{3}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
CatalogSupplier = Literal["mock", "khommo", "vietshare"]
LiveCatalogSupplier = Literal["khommo", "vietshare"]
LiveCatalogSelection = Literal["all", "khommo", "vietshare"]
CatalogSelection = Literal["all", "mock", "khommo", "vietshare"]
CatalogMode = Literal["mock", "khommo-readonly", "vietshare-readonly"]
CatalogViewMode = Literal[
    "mock",
    "khommo-readonly",
    "vietshare-readonly",
    "multi-readonly",
]


class ContractModel(BaseModel):
    """Strict base settings shared by every public catalog model."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CatalogSourceOption(ContractModel):
    """One explicitly selectable normalized catalog source."""

    supplier: CatalogSupplier
    mode: CatalogMode
    read_only: Literal[True] = True

    @model_validator(mode="after")
    def mode_matches_supplier(self) -> CatalogSourceOption:
        expected: CatalogMode
        if self.supplier == "mock":
            expected = "mock"
        elif self.supplier == "khommo":
            expected = "khommo-readonly"
        else:
            expected = "vietshare-readonly"
        if self.mode != expected:
            raise ValueError("catalog source option must match its supplier mode")
        return self


class CatalogSourcesResponse(ContractModel):
    """Available sources plus whether clients must choose one explicitly."""

    sources: Annotated[tuple[CatalogSourceOption, ...], Field(min_length=1)]
    selection_required: StrictBool
    aggregate_available: StrictBool = False

    @model_validator(mode="after")
    def sources_are_unique_and_selection_is_honest(self) -> CatalogSourcesResponse:
        suppliers = [source.supplier for source in self.sources]
        if len(suppliers) != len(set(suppliers)):
            raise ValueError("catalog sources must be unique")
        if self.selection_required != (len(self.sources) > 1):
            raise ValueError("source selection requirement must match available sources")
        live_suppliers = {source.supplier for source in self.sources}
        expected_aggregate = live_suppliers == {"khommo", "vietshare"}
        if self.aggregate_available != expected_aggregate:
            raise ValueError("aggregate availability must match both configured live sources")
        return self


class Money(ContractModel):
    """An integer amount in an explicitly named currency and storage unit."""

    amount_minor: NonNegativeInt
    currency: CurrencyCode
    unit: Literal["minor"]

    def add(self, other: Money) -> Money:
        """Add only like-for-like money; implicit currency mixing is invalid."""
        if self.currency != other.currency or self.unit != other.unit:
            raise ValueError("money currency and unit must match")
        return Money(
            amount_minor=self.amount_minor + other.amount_minor,
            currency=self.currency,
            unit=self.unit,
        )


class SupplierProductIdentity(ContractModel):
    """The supplier's opaque identity for a product."""

    supplier_id: Identifier
    supplier_product_id: Identifier


class SupplierVariantIdentity(ContractModel):
    """The supplier's separate opaque identity for a variant."""

    supplier_id: Identifier
    supplier_variant_id: Identifier


class PendingMappingApproval(ContractModel):
    """A proposed supplier mapping that is not active."""

    status: Literal["pending"]


class ApprovedMappingApproval(ContractModel):
    """Evidence that an administrator explicitly approved a mapping."""

    status: Literal["approved"]
    approved_by_admin_id: Identifier
    approved_at: AwareDatetime


type MappingApproval = Annotated[
    PendingMappingApproval | ApprovedMappingApproval,
    Field(discriminator="status"),
]


class SupplierMapping(ContractModel):
    """A reviewed association between one normalized and one supplier variant."""

    supplier_product: SupplierProductIdentity
    supplier_variant: SupplierVariantIdentity
    approval: MappingApproval

    @model_validator(mode="after")
    def identities_belong_to_one_supplier(self) -> SupplierMapping:
        if self.supplier_product.supplier_id != self.supplier_variant.supplier_id:
            raise ValueError("supplier product and variant identities must share a supplier")
        return self

    @property
    def is_approved(self) -> bool:
        """Return whether explicit administrator evidence activates this mapping."""
        return isinstance(self.approval, ApprovedMappingApproval)


class CatalogVariant(ContractModel):
    """One normalized variant and its exact supplier mapping."""

    id: Identifier
    name: DisplayText
    mapping: SupplierMapping
    price: Money
    available_quantity: NonNegativeInt


class CatalogProduct(ContractModel):
    """A normalized product containing one or more distinct variants."""

    id: Identifier
    name: DisplayText
    description: DisplayText
    supplier: CatalogSupplier = "mock"
    mode: CatalogMode = "mock"
    read_only: Literal[True] = True
    price: Money
    available_quantity: NonNegativeInt
    variants: Annotated[tuple[CatalogVariant, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def variants_have_unique_identities(self) -> CatalogProduct:
        variant_ids = [variant.id for variant in self.variants]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("catalog variant ids must be unique within a product")

        supplier_variants = [
            (
                variant.mapping.supplier_variant.supplier_id,
                variant.mapping.supplier_variant.supplier_variant_id,
            )
            for variant in self.variants
        ]
        if len(supplier_variants) != len(set(supplier_variants)):
            raise ValueError("supplier variant identities must be unique within a product")

        primary_variant = self.variants[0]
        if self.price != primary_variant.price:
            raise ValueError("compatibility price must match the primary variant")
        if self.available_quantity != primary_variant.available_quantity:
            raise ValueError("compatibility quantity must match the primary variant")
        return self


class FreshnessStatus(StrEnum):
    """Whether a snapshot is within its declared maximum age."""

    FRESH = "fresh"
    STALE = "stale"


class CatalogFreshness(ContractModel):
    """Deterministic evidence used to derive fresh versus stale state."""

    status: FreshnessStatus
    observed_at: AwareDatetime
    evaluated_at: AwareDatetime
    max_age_seconds: PositiveInt

    @model_validator(mode="after")
    def status_matches_timestamps(self) -> CatalogFreshness:
        age = self.evaluated_at - self.observed_at
        if age < timedelta(0):
            raise ValueError("evaluated_at cannot be before observed_at")
        expected = (
            FreshnessStatus.STALE
            if age > timedelta(seconds=self.max_age_seconds)
            else FreshnessStatus.FRESH
        )
        if self.status is not expected:
            raise ValueError("freshness status does not match timestamps and max age")
        return self


class CatalogErrorCode(StrEnum):
    """Safe, non-secret catalog failure categories exposed to clients."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    UNSUPPORTED = "unsupported"


class CatalogError(ContractModel):
    """A client-safe error with an explicit retry decision."""

    code: CatalogErrorCode
    message: DisplayText
    retryable: StrictBool


class CatalogState(StrEnum):
    """Complete UI states represented by the catalog envelope."""

    FRESH = "fresh"
    STALE = "stale"
    EMPTY = "empty"
    ERROR = "error"


class CatalogResponse(ContractModel):
    """Catalog envelope with internally consistent freshness and error state."""

    mode: CatalogMode
    state: CatalogState
    freshness: CatalogFreshness | None
    items: tuple[CatalogProduct, ...]
    error: CatalogError | None
    supplier: CatalogSupplier = "mock"
    read_only: Literal[True] = True
    partial: StrictBool = False
    omitted_count: NonNegativeInt = 0

    @model_validator(mode="after")
    def state_is_consistent(self) -> CatalogResponse:
        if self.supplier == "mock":
            expected_mode: CatalogMode = "mock"
        elif self.supplier == "khommo":
            expected_mode = "khommo-readonly"
        else:
            expected_mode = "vietshare-readonly"
        if self.mode != expected_mode:
            raise ValueError("catalog supplier and mode must describe the same source")
        if any(
            item.supplier != self.supplier or item.mode != self.mode or not item.read_only
            for item in self.items
        ):
            raise ValueError("catalog items must match the envelope source and read-only state")
        if self.partial != (self.omitted_count > 0):
            raise ValueError("partial catalog state must match omitted item evidence")
        if self.partial and self.state not in {CatalogState.FRESH, CatalogState.STALE}:
            raise ValueError("only a populated catalog can be partial")

        if self.state is CatalogState.FRESH:
            if not self.items or self.freshness is None:
                raise ValueError("fresh catalog requires items and freshness evidence")
            if self.freshness.status is not FreshnessStatus.FRESH or self.error is not None:
                raise ValueError("fresh catalog cannot be stale or contain an error")
        elif self.state is CatalogState.STALE:
            if not self.items or self.freshness is None or self.error is None:
                raise ValueError("stale catalog requires cached items, freshness, and an error")
            if self.freshness.status is not FreshnessStatus.STALE:
                raise ValueError("stale catalog requires stale freshness evidence")
        elif self.state is CatalogState.EMPTY:
            if self.items or self.freshness is None:
                raise ValueError("empty catalog requires no items and freshness evidence")
            if self.freshness.status is not FreshnessStatus.FRESH or self.error is not None:
                raise ValueError("empty catalog must be a successful fresh read")
        elif self.state is CatalogState.ERROR:
            if self.items or self.freshness is not None or self.error is None:
                raise ValueError("error catalog requires only error evidence")
        return self


class AggregateCatalogState(StrEnum):
    """Whether the combined view is complete, degraded, empty, or unavailable."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    ERROR = "error"


class AggregateSourceReport(ContractModel):
    """Sanitized status for one source contributing to the combined view."""

    supplier: LiveCatalogSupplier
    mode: CatalogMode
    state: CatalogState
    freshness: CatalogFreshness | None
    error: CatalogError | None
    item_count: NonNegativeInt
    partial: StrictBool = False
    omitted_count: NonNegativeInt = 0

    @model_validator(mode="after")
    def report_is_consistent(self) -> AggregateSourceReport:
        expected_mode: CatalogMode = (
            "khommo-readonly" if self.supplier == "khommo" else "vietshare-readonly"
        )
        if self.mode != expected_mode:
            raise ValueError("aggregate source report must match its supplier mode")
        if self.partial != (self.omitted_count > 0):
            raise ValueError("aggregate source partial state must match omitted item evidence")
        if self.partial and self.state not in {CatalogState.FRESH, CatalogState.STALE}:
            raise ValueError("only a populated aggregate source can be partial")
        if self.state is CatalogState.ERROR:
            if self.item_count != 0 or self.freshness is not None or self.error is None:
                raise ValueError("aggregate error source requires only safe error evidence")
        elif self.state is CatalogState.EMPTY:
            if self.item_count != 0 or self.freshness is None or self.error is not None:
                raise ValueError("aggregate empty source requires successful freshness evidence")
            if self.freshness.status is not FreshnessStatus.FRESH:
                raise ValueError("aggregate empty source requires fresh evidence")
        else:
            if self.item_count == 0 or self.freshness is None:
                raise ValueError("aggregate populated source requires items and freshness evidence")
            if self.state is CatalogState.FRESH and self.error is not None:
                raise ValueError("aggregate fresh source cannot contain an error")
            if (
                self.state is CatalogState.FRESH
                and self.freshness.status is not FreshnessStatus.FRESH
            ):
                raise ValueError("aggregate fresh source requires fresh evidence")
            if self.state is CatalogState.STALE and self.error is None:
                raise ValueError("aggregate stale source requires safe error evidence")
            if (
                self.state is CatalogState.STALE
                and self.freshness.status is not FreshnessStatus.STALE
            ):
                raise ValueError("aggregate stale source requires stale evidence")
        return self


class AggregateCatalogResponse(ContractModel):
    """One read-only view over source-qualified products without deduplication."""

    supplier: Literal["aggregate"] = "aggregate"
    mode: Literal["multi-readonly"] = "multi-readonly"
    state: AggregateCatalogState
    items: tuple[CatalogProduct, ...]
    sources: Annotated[tuple[AggregateSourceReport, ...], Field(min_length=2)]
    read_only: Literal[True] = True
    partial: StrictBool
    omitted_count: NonNegativeInt

    @model_validator(mode="after")
    def aggregate_is_consistent(self) -> AggregateCatalogResponse:
        suppliers = [report.supplier for report in self.sources]
        if len(suppliers) != len(set(suppliers)):
            raise ValueError("aggregate source reports must be unique")
        if set(suppliers) != {"khommo", "vietshare"}:
            raise ValueError("aggregate requires the verified KhoMMO and VietShare sources")

        identities = [(item.supplier, item.id) for item in self.items]
        if len(identities) != len(set(identities)):
            raise ValueError("aggregate products must be unique by source-qualified identity")
        for report in self.sources:
            actual_count = sum(item.supplier == report.supplier for item in self.items)
            if actual_count != report.item_count:
                raise ValueError("aggregate item counts must match source reports")
        if any(
            item.supplier not in suppliers
            or item.mode
            != ("khommo-readonly" if item.supplier == "khommo" else "vietshare-readonly")
            for item in self.items
        ):
            raise ValueError("aggregate items must retain a configured live source")
        if self.omitted_count != sum(report.omitted_count for report in self.sources):
            raise ValueError("aggregate omitted count must equal known per-source omissions")

        degraded = any(
            report.partial or report.state in {CatalogState.STALE, CatalogState.ERROR}
            for report in self.sources
        )
        if self.items:
            expected_state = (
                AggregateCatalogState.PARTIAL if degraded else AggregateCatalogState.COMPLETE
            )
        elif all(report.state is CatalogState.EMPTY for report in self.sources):
            expected_state = AggregateCatalogState.EMPTY
        else:
            expected_state = AggregateCatalogState.ERROR
        if self.state is not expected_state:
            raise ValueError("aggregate state must match its per-source evidence")
        if self.partial != (self.state is AggregateCatalogState.PARTIAL):
            raise ValueError("aggregate partial flag must match aggregate state")
        return self


type CatalogListResponse = CatalogResponse | AggregateCatalogResponse


class CatalogDetailFound(ContractModel):
    """A supported catalog detail read that found a product."""

    state: Literal["found"]
    item: CatalogProduct


class CatalogDetailNotFound(ContractModel):
    """A supported detail read for an unknown normalized product id."""

    state: Literal["not_found"]
    product_id: Identifier


class CatalogDetailUnsupported(ContractModel):
    """An honest result for a supplier without a verified detail schema."""

    state: Literal["unsupported"]
    product_id: Identifier
    error: CatalogError

    @model_validator(mode="after")
    def error_is_unsupported(self) -> CatalogDetailUnsupported:
        if self.error.code is not CatalogErrorCode.UNSUPPORTED or self.error.retryable:
            raise ValueError("unsupported detail must use a non-retryable unsupported error")
        return self


type CatalogDetailResponse = Annotated[
    CatalogDetailFound | CatalogDetailNotFound | CatalogDetailUnsupported,
    Field(discriminator="state"),
]


class CapabilityStatus(StrEnum):
    """Availability of one narrow supplier-facing operation."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"


class Capability(ContractModel):
    """Capability state plus an explanation whenever it is unavailable."""

    status: CapabilityStatus
    reason: DisplayText | None

    @model_validator(mode="after")
    def unavailable_state_has_reason(self) -> Capability:
        if self.status is CapabilityStatus.ENABLED and self.reason is not None:
            raise ValueError("enabled capability cannot contain a disabled reason")
        if self.status is not CapabilityStatus.ENABLED and self.reason is None:
            raise ValueError("disabled or unsupported capability requires a reason")
        return self


class SupplierCapabilities(ContractModel):
    """Read capability truth with all money and delivery operations locked off."""

    catalog_read: Capability
    catalog_detail: Capability
    purchase: Capability
    payment: Capability
    top_up: Capability
    refund: Capability
    delivery: Capability

    @model_validator(mode="after")
    def write_capabilities_remain_disabled(self) -> SupplierCapabilities:
        restricted = (self.purchase, self.payment, self.top_up, self.refund, self.delivery)
        if any(capability.status is not CapabilityStatus.DISABLED for capability in restricted):
            raise ValueError("purchase, payment, top-up, refund, and delivery must stay disabled")
        return self
