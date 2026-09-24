"""Mock bot access remains bound to one synthetic local user."""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, MessageEntity, Update, User

from nyan_shop_bot.bot.mock_checkout import build_mock_checkout_dispatcher
from nyan_shop_bot.config import Settings
from nyan_shop_bot.orders.fakes import InMemoryOrderRepository
from tests.bot.test_offline_dispatch import RecordingSession


async def test_unauthorized_user_cannot_view_catalog_or_orders() -> None:
    repository = InMemoryOrderRepository()
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    dispatcher = build_mock_checkout_dispatcher(
        settings=settings, repository=repository, allowed_user_id=200
    )
    session = RecordingSession()
    bot = Bot(token="0:offline", session=session)
    for number, command in enumerate(("/catalog", "/orders"), start=1):
        message = Message(
            message_id=number,
            date=datetime(2026, 9, 25, tzinfo=UTC),
            chat=Chat(id=201, type="private"),
            from_user=User(id=201, is_bot=False, first_name="Other"),
            text=command,
            entities=(MessageEntity(type="bot_command", offset=0, length=len(command)),),
        )
        await dispatcher.feed_update(bot, Update(update_id=number, message=message))
    sent = [item for item in session.requests if isinstance(item, SendMessage)]
    assert len(sent) == 2
    assert all("không có quyền" in item.text for item in sent)
    assert await repository.list_recent() == ()
