"""Application service joining read-only supplier offers to local curation."""

from __future__ import annotations

import base64
import binascii
from typing import cast

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationDocument,
    CatalogCurationListing,
    CatalogCurationListingInput,
    CatalogCurationListingView,
    CatalogCurationOffer,
    CatalogCurationOfferRef,
    CatalogCurationSaveRequest,
    CatalogCurationWorkspace,
)
from nyan_shop_bot.catalog.curation.ports import CatalogCurationRepository
from nyan_shop_bot.catalog.models import (
    AggregateCatalogState,
    CatalogProduct,
    CatalogState,
    LiveCatalogSupplier,
)
from nyan_shop_bot.catalog.registry import CatalogRegistry


class UnknownCatalogOffer(ValueError):
    """An admin request referenced an offer absent from the current snapshot."""


def encode_offer_key(ref: CatalogCurationOfferRef) -> str:
    """Encode a reversible, URL-safe admin key without guessing identities."""
    encoded = base64.urlsafe_b64encode(ref.supplier_product_id.encode("utf-8")).decode("ascii")
    return f"{ref.supplier}.{encoded.rstrip('=')}"


def decode_offer_key(value: str) -> CatalogCurationOfferRef:
    """Decode only the exact canonical key shape produced above."""
    try:
        supplier_text, encoded = value.split(".", maxsplit=1)
        padding = "=" * (-len(encoded) % 4)
        product_id = base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
        if supplier_text not in {"khommo", "vietshare"}:
            raise ValueError("unknown supplier")
        ref = CatalogCurationOfferRef(
            supplier=cast(LiveCatalogSupplier, supplier_text),
            supplier_product_id=product_id,
        )
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise UnknownCatalogOffer("catalog offer key is invalid") from exc
    if encode_offer_key(ref) != value:
        raise UnknownCatalogOffer("catalog offer key is not canonical")
    return ref


class CatalogCurationService:
    """Keep supplier reads and local presentation writes explicitly separated."""

    def __init__(
        self,
        *,
        catalogs: CatalogRegistry,
        repository: CatalogCurationRepository,
    ) -> None:
        self._catalogs = catalogs
        self._repository = repository

    async def _read_products(self) -> tuple[tuple[CatalogProduct, ...], bool]:
        if self._catalogs.aggregate_available:
            response = await self._catalogs.read_aggregate()
            return (
                response.items,
                response.partial or response.state is AggregateCatalogState.ERROR,
            )

        products: list[CatalogProduct] = []
        partial = False
        for source in self._catalogs.sources:
            if source not in {"khommo", "vietshare"}:
                continue
            source_response = await self._catalogs.resolve(source).read_catalog()
            if source_response.state in {CatalogState.FRESH, CatalogState.STALE}:
                products.extend(source_response.items)
            partial = (
                partial or source_response.partial or source_response.state is CatalogState.ERROR
            )
        return tuple(products), partial

    @staticmethod
    def _listing_view(listing: CatalogCurationListing) -> CatalogCurationListingView:
        return CatalogCurationListingView(
            id=listing.id,
            name=listing.name,
            description=listing.description,
            category=listing.category,
            visible=listing.visible,
            sort_order=listing.sort_order,
            retail_price=listing.retail_price,
            offer_keys=tuple(encode_offer_key(ref) for ref in listing.offer_refs),
        )

    @staticmethod
    def _workspace_from(
        document: CatalogCurationDocument,
        products: tuple[CatalogProduct, ...],
        *,
        source_partial: bool,
    ) -> CatalogCurationWorkspace:
        assigned = {ref: listing.id for listing in document.listings for ref in listing.offer_refs}
        offers: list[CatalogCurationOffer] = []
        resolved: set[CatalogCurationOfferRef] = set()
        for product in products:
            if product.supplier not in {"khommo", "vietshare"}:
                continue
            supplier: LiveCatalogSupplier = product.supplier
            ref = CatalogCurationOfferRef(
                supplier=supplier,
                supplier_product_id=product.id,
            )
            resolved.add(ref)
            offers.append(
                CatalogCurationOffer(
                    key=encode_offer_key(ref),
                    supplier=supplier,
                    supplier_product_id=product.id,
                    name=product.name,
                    description=product.description,
                    price=product.price,
                    available_quantity=product.available_quantity,
                    assigned_listing_id=assigned.get(ref),
                )
            )
        persisted_refs = {ref for listing in document.listings for ref in listing.offer_refs}
        listings = tuple(
            CatalogCurationService._listing_view(listing)
            for listing in sorted(document.listings, key=lambda item: (item.sort_order, item.id))
        )
        return CatalogCurationWorkspace(
            revision=document.revision,
            offers=tuple(offers),
            listings=listings,
            unresolved_offer_count=len(persisted_refs - resolved),
            source_partial=source_partial,
        )

    async def get_workspace(self) -> CatalogCurationWorkspace:
        document = await self._repository.load()
        products, partial = await self._read_products()
        return self._workspace_from(document, products, source_partial=partial)

    @staticmethod
    def _persisted_listing(value: CatalogCurationListingInput) -> CatalogCurationListing:
        return CatalogCurationListing(
            id=value.id,
            name=value.name,
            description=value.description,
            category=value.category,
            visible=value.visible,
            sort_order=value.sort_order,
            retail_price=value.retail_price,
            offer_refs=tuple(decode_offer_key(key) for key in value.offer_keys),
        )

    async def save_workspace(
        self,
        request: CatalogCurationSaveRequest,
    ) -> CatalogCurationWorkspace:
        products, partial = await self._read_products()
        available = {
            CatalogCurationOfferRef(
                supplier=product.supplier,
                supplier_product_id=product.id,
            )
            for product in products
            if product.supplier in {"khommo", "vietshare"}
        }
        listings = tuple(self._persisted_listing(listing) for listing in request.listings)
        requested = {ref for listing in listings for ref in listing.offer_refs}
        if not requested.issubset(available):
            raise UnknownCatalogOffer("catalog offer is absent from the current read-only snapshot")
        document = await self._repository.save(
            expected_revision=request.expected_revision,
            listings=listings,
        )
        return self._workspace_from(document, products, source_partial=partial)
