"""Public catalog contracts for the mock foundation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Money(BaseModel):
    """Integer minor-unit money; floats and implicit currency are forbidden."""

    model_config = ConfigDict(frozen=True)

    amount_minor: int = Field(ge=0)
    currency: Literal["VND"]


class CatalogItem(BaseModel):
    """Synthetic product safe to expose in the local admin."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str
    supplier: Literal["mock"] = "mock"
    mode: Literal["mock"] = "mock"
    price: Money
    available_quantity: int = Field(ge=0)


class CatalogResponse(BaseModel):
    """Catalog envelope that makes the mock state impossible to miss."""

    mode: Literal["mock"] = "mock"
    items: list[CatalogItem]


class SupplierCapabilities(BaseModel):
    """Explicit capability flags; write operations are absent and disabled."""

    catalog_read: bool = True
    purchase: bool = False
    top_up: bool = False
    refund: bool = False
    delivery_credentials: bool = False
