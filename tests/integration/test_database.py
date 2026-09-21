"""PostgreSQL migration and connectivity evidence."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
async def test_migrations_are_at_head_and_tables_exist() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot",
    )
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            table_names = {
                name: await connection.scalar(text(f"SELECT to_regclass('public.{name}')::text"))
                for name in (
                    "catalog_items",
                    "order_intents",
                    "supplier_order_attempts",
                    "delivery_attempts",
                )
            }
    finally:
        await engine.dispose()

    assert revision == "20260921_0002"
    assert table_names == {name: name for name in table_names}
