"""PostgreSQL evidence for atomic curation replacement and conflicts."""

import asyncio
import json
import os
import re
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from nyan_shop_bot.catalog.curation.models import (
    CatalogCurationDocument,
    CatalogCurationListing,
    CatalogCurationOfferRef,
)
from nyan_shop_bot.catalog.curation.ports import (
    CatalogCurationRepositoryUnavailable,
    CatalogCurationRevisionConflict,
)
from nyan_shop_bot.catalog.curation.repository import PostgresCatalogCurationRepository
from nyan_shop_bot.catalog.models import Money

_TEST_SCHEMA_PATTERN = re.compile(r"^nyan_test_catalog_[0-9a-f]{32}$")


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


async def save_in_transaction(
    connection: AsyncConnection,
    *,
    expected_revision: int,
    value: CatalogCurationListing,
) -> CatalogCurationDocument:
    async with connection.begin():
        return await PostgresCatalogCurationRepository(connection).save(
            expected_revision=expected_revision,
            listings=(value,),
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


@pytest.mark.integration
async def test_repository_rejects_unknown_persisted_payload_fields() -> None:
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
                await connection.execute(
                    text(
                        """
                        INSERT INTO catalog_curation_documents
                            (id, revision, payload, created_at, updated_at)
                        VALUES
                            ('seller-catalog', 1, CAST(:payload AS jsonb), now(), now())
                        """
                    ),
                    {"payload": json.dumps({"listings": [], "unexpected": True})},
                )

                with pytest.raises(
                    CatalogCurationRepositoryUnavailable,
                    match="persisted curation payload is invalid",
                ):
                    await PostgresCatalogCurationRepository(connection).load()
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_same_revision_race_allows_exactly_one_postgres_commit() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot",
    )
    schema_name = f"nyan_test_catalog_{uuid4().hex}"
    if _TEST_SCHEMA_PATTERN.fullmatch(schema_name) is None:
        raise AssertionError("refusing to create an unguarded integration-test schema")
    quoted_schema = f'"{schema_name}"'
    admin_engine = create_async_engine(database_url, hide_parameters=True)
    isolated_engine: AsyncEngine | None = None
    schema_created = False
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            await connection.execute(
                text(
                    f"""
                    CREATE TABLE {quoted_schema}.catalog_curation_documents (
                        id VARCHAR(32) PRIMARY KEY,
                        revision BIGINT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
        schema_created = True
        isolated_engine = create_async_engine(
            database_url,
            hide_parameters=True,
            connect_args={"server_settings": {"search_path": schema_name}},
        )
        repository = PostgresCatalogCurationRepository(isolated_engine)
        assert (await repository.save(expected_revision=0, listings=(listing(),))).revision == 1

        left = listing().model_copy(update={"name": "Concurrent left"})
        right = listing().model_copy(update={"name": "Concurrent right"})
        async with (
            isolated_engine.connect() as left_connection,
            isolated_engine.connect() as right_connection,
        ):
            results = await asyncio.gather(
                save_in_transaction(
                    left_connection,
                    expected_revision=1,
                    value=left,
                ),
                save_in_transaction(
                    right_connection,
                    expected_revision=1,
                    value=right,
                ),
                return_exceptions=True,
            )

        assert sum(isinstance(result, CatalogCurationDocument) for result in results) == 1
        assert sum(isinstance(result, CatalogCurationRevisionConflict) for result in results) == 1
        stored = await repository.load()
        assert stored.revision == 2
        assert stored.listings[0].name in {left.name, right.name}
    finally:
        if isolated_engine is not None:
            await isolated_engine.dispose()
        if schema_created:
            if _TEST_SCHEMA_PATTERN.fullmatch(schema_name) is None:
                raise AssertionError("refusing to drop an unguarded integration-test schema")
            async with admin_engine.begin() as connection:
                await connection.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
        await admin_engine.dispose()
