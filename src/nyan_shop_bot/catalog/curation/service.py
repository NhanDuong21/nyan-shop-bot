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
from nyan_shop_bot.catalog.storefront.models import (
    StorefrontAvailability,
    StorefrontCatalogResponse,
    StorefrontCatalogState,
    StorefrontDetailFound,
    StorefrontDetailNotFound,
    StorefrontDetailResponse,
    StorefrontProduct,
)
from nyan_shop_bot.catalog.storefront.presentation import customer_text


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
            try:
                source_response = await self._catalogs.resolve(source).read_catalog()
            except Exception:
                partial = True
                continue
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

    async def read_storefront(self) -> StorefrontCatalogResponse:
        """Project visible owner listings without exposing supplier provenance."""
        document = await self._repository.load()
        visible_listings = tuple(
            listing
            for listing in sorted(document.listings, key=lambda item: (item.sort_order, item.id))
            if listing.visible and listing.retail_price is not None
        )
        if not visible_listings:
            return StorefrontCatalogResponse(
                revision=document.revision,
                state=StorefrontCatalogState.EMPTY,
                items=(),
                partial=False,
                unresolved_offer_count=0,
                source_evidence_partial=False,
            )

        products, source_partial = await self._read_products()
        resolved: dict[CatalogCurationOfferRef, CatalogProduct] = {}
        for product in products:
            if product.supplier not in {"khommo", "vietshare"}:
                continue
            ref = CatalogCurationOfferRef(
                supplier=product.supplier,
                supplier_product_id=product.id,
            )
            resolved[ref] = product

        items: list[StorefrontProduct] = []
        unresolved_offer_count = 0
        for listing in visible_listings:
            retail_price = listing.retail_price
            if retail_price is None:
                continue
            linked = tuple(resolved.get(ref) for ref in listing.offer_refs)
            unresolved = sum(product is None for product in linked)
            unresolved_offer_count += unresolved
            known = tuple(product for product in linked if product is not None)
            if any(product.available_quantity > 0 for product in known):
                availability = StorefrontAvailability.IN_STOCK
            elif unresolved == 0:
                availability = StorefrontAvailability.OUT_OF_STOCK
            else:
                availability = StorefrontAvailability.UNKNOWN
            items.append(
                StorefrontProduct(
                    id=listing.id,
                    name=customer_text(listing.name),
                    description=customer_text(listing.description),
                    category=(
                        None if listing.category is None else customer_text(listing.category)
                    ),
                    price=retail_price,
                    availability=availability,
                )
            )

        partial = source_partial or unresolved_offer_count > 0
        return StorefrontCatalogResponse(
            revision=document.revision,
            state=(StorefrontCatalogState.PARTIAL if partial else StorefrontCatalogState.READY),
            items=tuple(items),
            partial=partial,
            unresolved_offer_count=unresolved_offer_count,
            source_evidence_partial=source_partial,
        )

    async def get_storefront_product(self, product_id: str) -> StorefrontDetailResponse:
        """Resolve detail from the same current customer-safe projection."""
        response = await self.read_storefront()
        item = next((item for item in response.items if item.id == product_id), None)
        if item is None:
            return StorefrontDetailNotFound(state="not_found", product_id=product_id)
        return StorefrontDetailFound(state="found", item=item)

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
