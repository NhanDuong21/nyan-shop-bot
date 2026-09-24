"""PostgreSQL evidence for atomic curation replacement and conflicts."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationListing,
    CatalogCurationOfferRef,
)
from nyan_shop_bot.catalog.curation.ports import CatalogCurationRevisionConflict
from nyan_shop_bot.catalog.curation.repository import PostgresCatalogCurationRepository
from nyan_shop_bot.catalog.models import Money


def listing() -> CatalogCurationListing:
    return CatalogCurationListing(
        id="integration-listing",
        name="Sản phẩm tích hợp",
        description="Dữ liệu tổng hợp dùng riêng trong transaction kiểm thử.",
        category="Kiểm thử",
        visible=True,
        sort_order=0,
        retail_price=Money(amount_minor=25_000, currency="VND", unit="minor"),
        offer_refs=(
            CatalogCurationOfferRef(
                supplier="khommo",
                supplier_product_id="integration-source",
            ),
        ),
    )


@pytest.mark.integration
async def test_repository_insert_update_and_revision_conflict_are_atomic() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot",
    )
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text("DELETE FROM catalog_curation_documents WHERE id = 'seller-catalog'")
                )
                repository = PostgresCatalogCurationRepository(connection)

                assert (await repository.load()).revision == 0
                first = await repository.save(expected_revision=0, listings=(listing(),))
                assert first.revision == 1
                assert (await repository.load()) == first

                second = await repository.save(
                    expected_revision=1,
                    listings=(first.listings[0].model_copy(update={"visible": False}),),
                )
                assert second.revision == 2
                assert second.listings[0].visible is False

                with pytest.raises(CatalogCurationRevisionConflict):
                    await repository.save(expected_revision=1, listings=(listing(),))
                assert (await repository.load()) == second
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
