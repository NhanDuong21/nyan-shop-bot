"""API and offline Telegram share PostgreSQL order state without any transport."""

from __future__ import annotations

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Update, User
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nyan_shop_bot.bot.mock_checkout import build_mock_checkout_dispatcher
from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import create_app
from nyan_shop_bot.orders.repository import PostgresOrderRepository
from tests.bot.test_offline_dispatch import RecordingSession, _message

TOKEN = "synthetic-postgres-demo-key-00000000000001"


class ReadyDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.mark.integration
async def test_postgres_is_shared_by_http_and_duplicate_offline_bot_callbacks(
    postgres_engine: AsyncEngine,
    postgres_sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, mock_checkout_access_token=TOKEN)  # type: ignore[call-arg]
    bot_repository = PostgresOrderRepository(postgres_sessions)
    api_repository = PostgresOrderRepository(postgres_sessions)
    dispatcher = build_mock_checkout_dispatcher(
        settings=settings, repository=bot_repository, allowed_user_id=200
    )
    session = RecordingSession()
    bot = Bot(token="0:offline", session=session)
    await dispatcher.feed_update(bot, Update(update_id=1, message=_message("/catalog", 1)))
    catalog_message = next(item for item in session.requests if isinstance(item, SendMessage))
    assert catalog_message.reply_markup is not None
    callback_data = catalog_message.reply_markup.inline_keyboard[0][0].callback_data

    for update_id in (2, 3):
        callback = CallbackQuery(
            id=f"duplicate-{update_id}",
            from_user=User(id=200, is_bot=False, first_name="Offline"),
            chat_instance="offline-chat",
            message=_message("mock catalog", 55),
            data=callback_data,
        )
        await dispatcher.feed_update(bot, Update(update_id=update_id, callback_query=callback))
    await dispatcher.feed_update(bot, Update(update_id=4, message=_message("/orders", 4)))
    sent = [item for item in session.requests if isinstance(item, SendMessage)]
    assert len(sent) == 4
    assert "SUCCEEDED" in sent[1].text
    assert sent[1].text == sent[2].text
    assert "LỊCH SỬ ĐƠN MOCK" in sent[3].text

    application = create_app(
        settings=settings,
        catalog=FakeCatalogReader(),
        database=ReadyDatabase(),
        order_repository=api_repository,
    )
    async with AsyncClient(
        transport=ASGITransport(app=application, client=("127.0.0.1", 12345)),
        base_url="http://localhost",
    ) as api:
        response = await api.get(
            "/api/v1/mock-checkout/orders", headers={"Authorization": f"Bearer {TOKEN}"}
        )
    assert response.status_code == 200
    orders = response.json()
    assert len(orders) == 1
    assert orders[0]["purchase_state"] == "SUCCEEDED"
    assert orders[0]["unit_price"] == {"amount_minor": 49000, "currency": "VND", "unit": "minor"}

    async with postgres_engine.connect() as connection:
        intents = await connection.scalar(text("SELECT count(*) FROM order_intents"))
        attempts = await connection.scalar(text("SELECT count(*) FROM supplier_order_attempts"))
    assert intents == attempts == 1
