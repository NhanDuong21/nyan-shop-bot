"""Transactional, cross-instance, recovery, and delivery PostgreSQL tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nyan_shop_bot.orders.errors import IdempotencyConflict
from nyan_shop_bot.orders.fakes import (
    FakeDeliveryOutcome,
    FakeDeliverySink,
    FakePurchaseOutcome,
    FakeSupplierPort,
)
from nyan_shop_bot.orders.models import DeliveryState, PurchaseState
from nyan_shop_bot.orders.repository import PostgresOrderRepository
from tests.integration.orders.support import prepared_candidate, request, service


@pytest.mark.integration
async def test_intent_and_prepared_attempt_are_persisted_atomically(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    repository = PostgresOrderRepository(postgres_sessions)
    candidate = prepared_candidate(key="atomic-prepare", cap=60_000)
    result = await repository.prepare(candidate)

    async with postgres_engine.connect() as connection:
        intent = (
            (
                await connection.execute(
                    text(
                        "SELECT purchase_state, unit_price_minor, "
                        "max_unit_price_minor FROM order_intents"
                    )
                )
            )
            .mappings()
            .one()
        )
        attempt = (
            (
                await connection.execute(
                    text(
                        "SELECT status, request_key, request_fingerprint, "
                        "request_payload FROM supplier_order_attempts"
                    )
                )
            )
            .mappings()
            .one()
        )

    assert result.created
    assert intent == {
        "purchase_state": "PREPARED",
        "unit_price_minor": 49_000,
        "max_unit_price_minor": 60_000,
    }
    assert attempt["status"] == "PREPARED"
    assert attempt["request_key"] == candidate.supplier_attempt.request_key
    assert attempt["request_fingerprint"] == candidate.supplier_attempt.request_fingerprint
    assert attempt["request_payload"] == candidate.supplier_attempt.request_payload.as_dict()


@pytest.mark.integration
async def test_attempt_insert_failure_rolls_back_new_intent(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    repository = PostgresOrderRepository(postgres_sessions)
    first = prepared_candidate(key="rollback-first")
    await repository.prepare(first)
    second = prepared_candidate(key="rollback-second")
    colliding = replace(
        second,
        supplier_attempt=replace(second.supplier_attempt, id=first.supplier_attempt.id),
    )

    with pytest.raises(IntegrityError):
        await repository.prepare(colliding)

    async with postgres_engine.connect() as connection:
        keys = list(
            (
                await connection.execute(
                    text("SELECT idempotency_key FROM order_intents ORDER BY idempotency_key")
                )
            ).scalars()
        )
        attempt_count = await connection.scalar(
            text("SELECT count(*) FROM supplier_order_attempts")
        )
    assert keys == ["rollback-first"]
    assert attempt_count == 1


@pytest.mark.integration
async def test_cross_instance_duplicate_click_creates_one_obligation(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    first_supplier = FakeSupplierPort()
    second_supplier = FakeSupplierPort()
    first_service = service(
        PostgresOrderRepository(postgres_sessions),
        supplier=first_supplier,
    )
    second_service = service(
        PostgresOrderRepository(postgres_sessions),
        supplier=second_supplier,
    )
    order_request = request(key="cross-instance")

    first, second = await asyncio.gather(
        first_service.place_order(
            customer_reference="synthetic-customer",
            request=order_request,
        ),
        second_service.place_order(
            customer_reference="synthetic-customer",
            request=order_request,
        ),
    )
    final = await PostgresOrderRepository(postgres_sessions).get(first.intent_id)

    async with postgres_engine.connect() as connection:
        intent_count = await connection.scalar(text("SELECT count(*) FROM order_intents"))
        attempt_count = await connection.scalar(
            text("SELECT count(*) FROM supplier_order_attempts")
        )
    assert first.intent_id == second.intent_id
    assert final.intent.purchase_state is PurchaseState.SUCCEEDED
    assert first_supplier.purchase_calls + second_supplier.purchase_calls == 1
    assert intent_count == attempt_count == 1


@pytest.mark.integration
async def test_payload_conflict_cannot_overwrite_or_add_attempt(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    supplier = FakeSupplierPort()
    order_service = service(PostgresOrderRepository(postgres_sessions), supplier=supplier)
    await order_service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="database-conflict", quantity=1),
    )
    with pytest.raises(IdempotencyConflict):
        await order_service.place_order(
            customer_reference="synthetic-customer",
            request=request(key="database-conflict", quantity=2),
        )

    async with postgres_engine.connect() as connection:
        intent_count = await connection.scalar(text("SELECT count(*) FROM order_intents"))
        attempt_count = await connection.scalar(
            text("SELECT count(*) FROM supplier_order_attempts")
        )
        quantity = await connection.scalar(text("SELECT quantity FROM order_intents"))
    assert intent_count == attempt_count == 1
    assert quantity == 1
    assert supplier.purchase_calls == 1


@pytest.mark.integration
async def test_database_enforces_one_supplier_attempt_per_intent(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    repository = PostgresOrderRepository(postgres_sessions)
    candidate = prepared_candidate(key="one-attempt")
    await repository.prepare(candidate)

    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        """
                        INSERT INTO supplier_order_attempts (
                            id, order_intent_id, supplier_code, request_key,
                            request_fingerprint, request_payload, status
                        ) VALUES (
                            'duplicate-attempt', :intent_id, 'fake-supplier',
                            'different-request-key', :fingerprint,
                            CAST(:payload AS jsonb), 'PREPARED'
                        )
                        """
                    ),
                    {
                        "intent_id": candidate.intent.id,
                        "fingerprint": "a" * 64,
                        "payload": "{}",
                    },
                )
        finally:
            await transaction.rollback()


@pytest.mark.integration
async def test_unknown_and_reconciling_survive_repository_recreation(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    supplier = FakeSupplierPort(
        purchase_outcome=FakePurchaseOutcome.ACCEPTED,
        reconciliation=False,
    )
    first_service = service(
        PostgresOrderRepository(postgres_sessions),
        supplier=supplier,
    )
    unknown = await first_service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="persisted-uncertainty"),
    )
    assert unknown.purchase_state is PurchaseState.UNKNOWN

    recreated_service = service(
        PostgresOrderRepository(postgres_sessions),
        supplier=supplier,
    )
    reconciling = await recreated_service.recover(unknown.intent_id)

    async with postgres_engine.connect() as connection:
        states = (
            await connection.execute(
                text(
                    "SELECT i.purchase_state, a.status "
                    "FROM order_intents i JOIN supplier_order_attempts a "
                    "ON a.order_intent_id = i.id"
                )
            )
        ).one()
    assert reconciling.purchase_state is PurchaseState.RECONCILING
    assert tuple(states) == ("RECONCILING", "RECONCILING")
    assert supplier.purchase_calls == 1
    assert supplier.reconciliation_calls == 0


@pytest.mark.integration
async def test_delivery_numbering_is_independent_across_repository_instances(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    supplier = FakeSupplierPort()
    purchase_service = service(
        PostgresOrderRepository(postgres_sessions),
        supplier=supplier,
    )
    purchased = await purchase_service.place_order(
        customer_reference="synthetic-customer",
        request=request(key="delivery-numbering"),
    )
    first_delivery = FakeDeliverySink((FakeDeliveryOutcome.FAILURE,))
    second_delivery = FakeDeliverySink((FakeDeliveryOutcome.SUCCESS,))
    first_service = service(
        PostgresOrderRepository(postgres_sessions),
        supplier=supplier,
        delivery=first_delivery,
    )
    second_service = service(
        PostgresOrderRepository(postgres_sessions),
        supplier=supplier,
        delivery=second_delivery,
    )

    await first_service.deliver(purchased.intent_id)
    final = await second_service.deliver(purchased.intent_id)

    async with postgres_engine.connect() as connection:
        numbers = list(
            (
                await connection.execute(
                    text("SELECT attempt_number FROM delivery_attempts ORDER BY attempt_number")
                )
            ).scalars()
        )
        supplier_attempts = await connection.scalar(
            text("SELECT count(*) FROM supplier_order_attempts")
        )
    assert numbers == [1, 2]
    assert [item.status for item in final.deliveries] == [
        DeliveryState.FAILED,
        DeliveryState.SUCCEEDED,
    ]
    assert supplier_attempts == 1
    assert supplier.purchase_calls == 1
