"""Strict invariants for the owner-curated catalog document."""

import pytest
from pydantic import ValidationError

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationDocument,
    CatalogCurationListing,
    CatalogCurationOfferRef,
)
from nyan_shop_bot.catalog.models import Money


def listing(
    identifier: str = "nyan-learning",
    *,
    description: str = "Mô tả do chủ shop biên tập.",
    supplier: str = "khommo",
    product_id: str = "source-learning",
    sort_order: int = 0,
    visible: bool = False,
    retail_price: Money | None = None,
) -> CatalogCurationListing:
    return CatalogCurationListing(
        id=identifier,
        name="Gói học tập Nyan",
        description=description,
        category="Học tập",
        visible=visible,
        sort_order=sort_order,
        retail_price=retail_price,
        offer_refs=(
            CatalogCurationOfferRef(
                supplier=supplier,
                supplier_product_id=product_id,
            ),
        ),
    )


def test_document_preserves_integer_vnd_and_explicit_offer_reference() -> None:
    value = CatalogCurationDocument(
        revision=3,
        listings=(
            listing(
                visible=True,
                retail_price=Money(amount_minor=125_000, currency="VND", unit="minor"),
            ),
        ),
    )

    assert value.listings[0].retail_price is not None
    assert value.listings[0].retail_price.amount_minor == 125_000
    assert value.listings[0].offer_refs[0].supplier == "khommo"


def test_visible_listing_requires_price_and_price_is_vnd_only() -> None:
    with pytest.raises(ValidationError, match="visible listing requires"):
        listing(visible=True)
    with pytest.raises(ValidationError, match="must use VND"):
        listing(retail_price=Money(amount_minor=100, currency="USD", unit="minor"))
    with pytest.raises(ValidationError):
        Money.model_validate({"amount_minor": 1.5, "currency": "VND", "unit": "minor"})


def test_document_rejects_duplicate_offer_assignment_and_sort_order() -> None:
    with pytest.raises(ValidationError, match="one supplier offer"):
        CatalogCurationDocument(
            revision=1,
            listings=(
                listing("nyan-one"),
                listing("nyan-two", sort_order=1),
            ),
        )
    with pytest.raises(ValidationError, match="sort orders"):
        CatalogCurationDocument(
            revision=1,
            listings=(
                listing("nyan-one", product_id="offer-one"),
                listing("nyan-two", product_id="offer-two"),
            ),
        )


@pytest.mark.parametrize(
    "invalid",
    [" Leading", "Trailing ", "line\nbreak", "decomposed-e\u0301"],
)
def test_owner_authored_display_text_fails_closed(invalid: str) -> None:
    with pytest.raises(ValidationError):
        CatalogCurationListing(
            id="nyan-invalid",
            name=invalid,
            description="Mô tả hợp lệ.",
            category=None,
            visible=False,
            sort_order=0,
            retail_price=None,
            offer_refs=(
                CatalogCurationOfferRef(
                    supplier="vietshare",
                    supplier_product_id="source-id",
                ),
            ),
        )


def test_owner_authored_description_allows_lf_but_rejects_other_controls() -> None:
    value = listing(description="Dòng mô tả thứ nhất.\nDòng mô tả thứ hai.")

    assert value.description == "Dòng mô tả thứ nhất.\nDòng mô tả thứ hai."

    for invalid in ("Có tab\tkhông hợp lệ.", "Có carriage return\rkhông hợp lệ."):
        with pytest.raises(ValidationError, match="unsupported control character"):
            listing(description=invalid)
