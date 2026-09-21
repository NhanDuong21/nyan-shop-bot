"""Migration head, table, state, and uniqueness contract evidence."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.orders.support import require_disposable_order_database_url


@pytest.mark.integration
@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql+asyncpg://synthetic:synthetic@db.example.invalid:5432/shop",
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/other",
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot?ssl=require",
    ),
)
def test_order_fixture_rejects_unapproved_database(database_url: str) -> None:
    with pytest.raises(RuntimeError, match="unapproved order integration database"):
        require_disposable_order_database_url(database_url)


@pytest.mark.integration
async def test_order_migration_is_head_with_expected_tables_and_constraints(
    postgres_engine: AsyncEngine,
) -> None:
    async with postgres_engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        table_names = {
            name: await connection.scalar(text(f"SELECT to_regclass('public.{name}')::text"))
            for name in (
                "order_intents",
                "supplier_order_attempts",
                "delivery_attempts",
            )
        }
        constraints = set(
            (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid IN ("
                        "'order_intents'::regclass, "
                        "'supplier_order_attempts'::regclass, "
                        "'delivery_attempts'::regclass)"
                    )
                )
            ).scalars()
        )

    assert revision == "20260921_0002"
    assert table_names == {name: name for name in table_names}
    assert {
        "uq_order_intents_idempotency_key",
        "uq_supplier_order_attempts_order_intent",
        "uq_supplier_order_attempts_request_key",
        "uq_delivery_attempts_order_number",
        "uq_delivery_attempts_delivery_key",
        "ck_order_intents_purchase_state",
        "ck_supplier_order_attempts_status",
        "ck_delivery_attempts_status",
    } <= constraints


@pytest.mark.integration
@pytest.mark.parametrize(
    ("purchase_state", "quantity", "unit_price", "max_price"),
    (
        ("NOT_A_STATE", 1, 100, 100),
        ("PREPARED", 0, 100, 100),
        ("PREPARED", 1, -1, 100),
        ("PREPARED", 1, 101, 100),
    ),
)
async def test_database_rejects_invalid_state_quantity_and_money(
    postgres_engine: AsyncEngine,
    purchase_state: str,
    quantity: int,
    unit_price: int,
    max_price: int,
) -> None:
    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        """
                        INSERT INTO order_intents (
                            id, idempotency_key, customer_reference, product_id,
                            variant_id, quantity, unit_price_minor,
                            max_unit_price_minor, currency, money_unit,
                            purchase_state
                        ) VALUES (
                            :id, :key, 'synthetic-customer', 'mock-product',
                            'mock-variant', :quantity, :unit_price, :max_price,
                            'VND', 'minor', :purchase_state
                        )
                        """
                    ),
                    {
                        "id": f"schema-{purchase_state}-{quantity}-{unit_price}",
                        "key": f"schema-{purchase_state}-{quantity}-{unit_price}",
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "max_price": max_price,
                        "purchase_state": purchase_state,
                    },
                )
        finally:
            await transaction.rollback()
