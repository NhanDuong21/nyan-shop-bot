"""PostgreSQL migration and connectivity evidence."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
async def test_initial_migration_is_at_head_and_table_exists() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot",
    )
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            table_name = await connection.scalar(
                text("SELECT to_regclass('public.catalog_items')::text")
            )
    finally:
        await engine.dispose()

    assert revision == "20260919_0001"
    assert table_name == "catalog_items"
