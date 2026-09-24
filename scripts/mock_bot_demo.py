"""Exercise the Telegram mock checkout through an offline session only."""

# ruff: noqa: E402 - add the repository's src directory before importing the app

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User
from sqlalchemy.ext.asyncio import async_sessionmaker

from nyan_shop_bot.bot.mock_checkout import build_mock_checkout_dispatcher
from nyan_shop_bot.config import Settings
from nyan_shop_bot.database import PostgresDatabase
from nyan_shop_bot.orders.repository import PostgresOrderRepository


class OfflineSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - aiogram interface
    ) -> Any:
        del bot, timeout
        self.sent.append(method)
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 - aiogram interface
        chunk_size: int = 65_536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        del url, headers, timeout, chunk_size, raise_for_status
        if False:
            yield b""


def message(text: str, message_id: int) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=200, type="private"),
        from_user=User(id=200, is_bot=False, first_name="Demo"),
        text=text,
        entities=(MessageEntity(type="bot_command", offset=0, length=len(text)),)
        if text.startswith("/")
        else (),
    )


async def run(scenario: str) -> None:
    os.environ.update(
        APP_ENV="local",
        APP_HOST="127.0.0.1",
        SUPPLIER_MODE="mock",
        PAYMENT_MODE="disabled",
        ALLOW_REAL_PURCHASES="false",
    )
    settings = Settings()
    database = PostgresDatabase(settings.database_url)
    try:
        repository = PostgresOrderRepository(async_sessionmaker(database.engine))
        dispatcher = build_mock_checkout_dispatcher(
            settings=settings, repository=repository, allowed_user_id=200
        )
        session = OfflineSession()
        bot = Bot(token="0:offline", session=session)
        await dispatcher.feed_update(bot, Update(update_id=1, message=message("/catalog", 1)))
        catalog_sent = next(item for item in session.sent if isinstance(item, SendMessage))
        if catalog_sent.reply_markup is None:
            raise RuntimeError("Mock catalog has no available checkout action")
        scenario_index = {"success": 0, "failed_safe": 1, "unknown": 2}[scenario]
        callback_data = catalog_sent.reply_markup.inline_keyboard[scenario_index][0].callback_data
        callback = CallbackQuery(
            id="offline-demo",
            from_user=User(id=200, is_bot=False, first_name="Demo"),
            chat_instance="offline-demo",
            message=message("mock catalog", secrets.randbelow(1_000_000_000) + 1),
            data=callback_data,
        )
        await dispatcher.feed_update(bot, Update(update_id=2, callback_query=callback))
        await dispatcher.feed_update(bot, Update(update_id=3, message=message("/orders", 3)))
        for sent in session.sent:
            if isinstance(sent, SendMessage):
                print(sent.text)
                print()
    finally:
        await database.close()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("success", "failed_safe", "unknown"))
    args = parser.parse_args()
    asyncio.run(run(args.scenario))


if __name__ == "__main__":
    main()
