"""PostgreSQL migration and connectivity evidence."""

import os
from collections.abc import Mapping

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalid_values",
    (
        {"unit_price_minor": 101, "max_unit_price_minor": 100},
        {"currency": ""},
        {"currency": "usd"},
        {"currency": "USDX"},
        {"money_unit": ""},
        {"money_unit": "major"},
    ),
)
async def test_order_intent_money_constraints_are_enforced(
    invalid_values: Mapping[str, object],
) -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot",
    )
    values: dict[str, object] = {
        "id": "constraint-probe",
        "idempotency_key": "constraint-probe",
        "customer_reference": "synthetic-customer",
        "product_id": "mock-product",
        "variant_id": "mock-variant",
        "quantity": 1,
        "unit_price_minor": 100,
        "max_unit_price_minor": 100,
        "currency": "VND",
        "money_unit": "minor",
        "purchase_state": "PREPARED",
    }
    values.update(invalid_values)
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                with pytest.raises(IntegrityError):
                    await connection.execute(
                        text(
                            """
                            INSERT INTO order_intents (
                                id,
                                idempotency_key,
                                customer_reference,
                                product_id,
                                variant_id,
                                quantity,
                                unit_price_minor,
                                max_unit_price_minor,
                                currency,
                                money_unit,
                                purchase_state
                            ) VALUES (
                                :id,
                                :idempotency_key,
                                :customer_reference,
                                :product_id,
                                :variant_id,
                                :quantity,
                                :unit_price_minor,
                                :max_unit_price_minor,
                                :currency,
                                :money_unit,
                                :purchase_state
                            )
                            """
                        ),
                        values,
                    )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
