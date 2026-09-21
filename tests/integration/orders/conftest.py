"""Isolated order-table fixtures for the local PostgreSQL test database."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.integration.orders.support import (
    DISPOSABLE_ORDER_DATABASE_URL,
    require_disposable_order_database_url,
)


@pytest.fixture
async def postgres_engine() -> AsyncIterator[AsyncEngine]:
    database_url = require_disposable_order_database_url(
        os.environ.get("DATABASE_URL", DISPOSABLE_ORDER_DATABASE_URL)
    )
    engine = create_async_engine(database_url, hide_parameters=True)
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE delivery_attempts, supplier_order_attempts, order_intents")
        )
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE TABLE delivery_attempts, supplier_order_attempts, order_intents")
            )
        await engine.dispose()


@pytest.fixture
def postgres_sessions(
    postgres_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(postgres_engine, expire_on_commit=False)
