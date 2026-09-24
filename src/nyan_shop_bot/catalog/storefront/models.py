"""Strict customer-facing contracts for the curated Nyan catalog.

Supplier provenance deliberately does not exist in these models. They contain
only owner-authored presentation fields and conservative availability derived
from read-only evidence.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from nyan_shop_bot.catalog.models import Money

StorefrontProductId = Annotated[
    StrictStr,
    Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]
StorefrontName = Annotated[StrictStr, Field(min_length=1, max_length=255)]
StorefrontDescription = Annotated[StrictStr, Field(min_length=1, max_length=4000)]
StorefrontCategory = Annotated[StrictStr, Field(min_length=1, max_length=96)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class StorefrontModel(BaseModel):
    """Fail closed on unknown customer-facing fields and mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StorefrontAvailability(StrEnum):
    """Conservative stock state without exposing exact supplier inventory."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class StorefrontCatalogState(StrEnum):
    """Whether the persisted storefront has complete read-only evidence."""

    READY = "ready"
    PARTIAL = "partial"
    EMPTY = "empty"


class StorefrontProduct(StorefrontModel):
    """One visible Nyan listing with no supplier identity or source price."""

    id: StorefrontProductId
    name: StorefrontName
    description: StorefrontDescription
    category: StorefrontCategory | None
    price: Money
    availability: StorefrontAvailability
    read_only: Literal[True] = True

    @model_validator(mode="after")
    def retail_price_is_vnd(self) -> Self:
        if self.price.currency != "VND":
            raise ValueError("storefront retail price must use VND")
        return self


class StorefrontCatalogResponse(StorefrontModel):
    """Versioned customer catalog with explicit degraded evidence."""

    revision: NonNegativeInt
    state: StorefrontCatalogState
    items: tuple[StorefrontProduct, ...]
    partial: StrictBool
    unresolved_offer_count: NonNegativeInt
    source_evidence_partial: StrictBool
    read_only: Literal[True] = True
    supplier_provenance_exposed: Literal[False] = False
    purchase_enabled: Literal[False] = False
    payment_enabled: Literal[False] = False

    @model_validator(mode="after")
    def state_is_consistent(self) -> Self:
        product_ids = [item.id for item in self.items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("storefront product ids must be unique")
        if self.partial != (self.state is StorefrontCatalogState.PARTIAL):
            raise ValueError("storefront partial flag must match its state")
        if self.state is StorefrontCatalogState.EMPTY:
            if self.items or self.unresolved_offer_count or self.source_evidence_partial:
                raise ValueError("empty storefront cannot contain product or source evidence")
        elif not self.items:
            raise ValueError("populated storefront state requires products")
        if self.state is StorefrontCatalogState.READY and (
            self.unresolved_offer_count or self.source_evidence_partial
        ):
            raise ValueError("ready storefront cannot contain incomplete source evidence")
        if self.state is StorefrontCatalogState.PARTIAL and not (
            self.unresolved_offer_count or self.source_evidence_partial
        ):
            raise ValueError("partial storefront requires incomplete source evidence")
        return self


class StorefrontDetailFound(StorefrontModel):
    """A current visible storefront product."""

    state: Literal["found"]
    item: StorefrontProduct


class StorefrontDetailNotFound(StorefrontModel):
    """A hidden, removed, or unknown storefront product."""

    state: Literal["not_found"]
    product_id: StorefrontProductId


StorefrontDetailResponse = Annotated[
    StorefrontDetailFound | StorefrontDetailNotFound,
    Field(discriminator="state"),
]
