"""Strict contracts for local seller-catalog curation.

The persisted document contains only owner-authored presentation fields and
explicit read-only supplier product references. It never represents approval
to purchase from a supplier.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from nyan_shop_bot.catalog.models import LiveCatalogSupplier, Money

MAX_DOCUMENT_BYTES = 1_000_000
MAX_LISTINGS = 500
MAX_OFFERS_PER_LISTING = 32

ListingId = Annotated[
    StrictStr,
    Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]
DisplayName = Annotated[StrictStr, Field(min_length=1, max_length=255)]
Description = Annotated[StrictStr, Field(min_length=1, max_length=4000)]
Category = Annotated[StrictStr, Field(min_length=1, max_length=96)]
SupplierProductId = Annotated[StrictStr, Field(min_length=1, max_length=256)]
OfferKey = Annotated[StrictStr, Field(min_length=1, max_length=512)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class CurationModel(BaseModel):
    """Fail closed on unknown fields and mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_display_text(value: str) -> str:
    if value != value.strip():
        raise ValueError("text cannot contain leading or trailing whitespace")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("text must use Unicode NFC normalization")
    if not value.isprintable():
        raise ValueError("text must contain printable characters only")
    return value


class CatalogCurationOfferRef(CurationModel):
    """One exact read-only supplier product reference."""

    supplier: LiveCatalogSupplier
    supplier_product_id: SupplierProductId

    @field_validator("supplier_product_id")
    @classmethod
    def validate_product_id(cls, value: str) -> str:
        return _validate_display_text(value)


class CatalogCurationListing(CurationModel):
    """One canonical Nyan listing persisted in the local database."""

    id: ListingId
    name: DisplayName
    description: Description
    category: Category | None
    visible: StrictBool
    sort_order: NonNegativeInt
    retail_price: Money | None
    offer_refs: Annotated[
        tuple[CatalogCurationOfferRef, ...],
        Field(min_length=1, max_length=MAX_OFFERS_PER_LISTING),
    ]

    @field_validator("name", "description")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_display_text(value)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        return None if value is None else _validate_display_text(value)

    @model_validator(mode="after")
    def validate_listing(self) -> Self:
        if len(self.offer_refs) != len(set(self.offer_refs)):
            raise ValueError("offer references must be unique within a listing")
        if self.retail_price is not None and self.retail_price.currency != "VND":
            raise ValueError("curated retail price must use VND")
        if self.visible and self.retail_price is None:
            raise ValueError("a visible listing requires a retail price")
        return self


class CatalogCurationDocument(CurationModel):
    """Versioned local persistence value."""

    revision: NonNegativeInt
    listings: Annotated[tuple[CatalogCurationListing, ...], Field(max_length=MAX_LISTINGS)]

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        listing_ids = [listing.id for listing in self.listings]
        if len(listing_ids) != len(set(listing_ids)):
            raise ValueError("listing ids must be unique")

        sort_orders = [listing.sort_order for listing in self.listings]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("listing sort orders must be unique")

        refs = [offer for listing in self.listings for offer in listing.offer_refs]
        if len(refs) != len(set(refs)):
            raise ValueError("one supplier offer cannot belong to multiple listings")

        if len(self.model_dump_json().encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError("catalog curation document exceeds the size limit")
        return self


class CatalogCurationListingInput(CurationModel):
    """Admin API listing shape using reversible offer keys."""

    id: ListingId
    name: DisplayName
    description: Description
    category: Category | None
    visible: StrictBool
    sort_order: NonNegativeInt
    retail_price: Money | None
    offer_keys: Annotated[
        tuple[OfferKey, ...],
        Field(min_length=1, max_length=MAX_OFFERS_PER_LISTING),
    ]

    @field_validator("name", "description")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_display_text(value)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        return None if value is None else _validate_display_text(value)

    @model_validator(mode="after")
    def validate_listing(self) -> Self:
        if len(self.offer_keys) != len(set(self.offer_keys)):
            raise ValueError("offer keys must be unique within a listing")
        if self.retail_price is not None and self.retail_price.currency != "VND":
            raise ValueError("curated retail price must use VND")
        if self.visible and self.retail_price is None:
            raise ValueError("a visible listing requires a retail price")
        return self


class CatalogCurationSaveRequest(CurationModel):
    """Complete optimistic replacement request."""

    expected_revision: NonNegativeInt
    listings: Annotated[tuple[CatalogCurationListingInput, ...], Field(max_length=MAX_LISTINGS)]

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        ids = [listing.id for listing in self.listings]
        if len(ids) != len(set(ids)):
            raise ValueError("listing ids must be unique")
        sort_orders = [listing.sort_order for listing in self.listings]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("listing sort orders must be unique")
        keys = [key for listing in self.listings for key in listing.offer_keys]
        if len(keys) != len(set(keys)):
            raise ValueError("one supplier offer cannot belong to multiple listings")
        if len(self.model_dump_json().encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError("catalog curation request exceeds the size limit")
        return self


class CatalogCurationOffer(CurationModel):
    """Sanitized read-only candidate exposed only to local admin."""

    key: OfferKey
    supplier: LiveCatalogSupplier
    supplier_product_id: SupplierProductId
    name: DisplayName
    description: Description
    price: Money
    available_quantity: NonNegativeInt
    assigned_listing_id: ListingId | None
    read_only: Literal[True] = True


class CatalogCurationListingView(CurationModel):
    """Canonical listing projected for the admin UI."""

    id: ListingId
    name: DisplayName
    description: Description
    category: Category | None
    visible: StrictBool
    sort_order: NonNegativeInt
    retail_price: Money | None
    offer_keys: Annotated[
        tuple[OfferKey, ...],
        Field(min_length=1, max_length=MAX_OFFERS_PER_LISTING),
    ]


class CatalogCurationWorkspace(CurationModel):
    """Complete local admin state without credentials or delivery data."""

    revision: NonNegativeInt
    offers: tuple[CatalogCurationOffer, ...]
    listings: tuple[CatalogCurationListingView, ...]
    unresolved_offer_count: NonNegativeInt
    source_partial: StrictBool
    read_only: Literal[True] = True
    supplier_writes_enabled: Literal[False] = False
