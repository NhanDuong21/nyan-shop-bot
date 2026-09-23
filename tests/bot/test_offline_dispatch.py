"""Aiogram dispatch works through an in-memory session and never opens transport."""

from __future__ import annotations

import socket
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User

from nyan_shop_bot.bot.callbacks import encode_quote_callback
from nyan_shop_bot.bot.handlers import (
    build_dispatcher,
    callback_handler,
    catalog_handler,
    orders_handler,
    start_handler,
    support_handler,
)
from nyan_shop_bot.catalog.mock import FakeCatalogReader, FakeCatalogScenario
from nyan_shop_bot.catalog.registry import CatalogRegistry


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> object:
        self.answers.append((text, kwargs))
        return object()

    @property
    def text(self) -> str:
        return self.answers[-1][0]


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message

    async def answer(self) -> object:
        return object()


class RecordingSession(BaseSession):
    """Satisfy aiogram's Bot boundary without DNS, sockets, or HTTP."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 - required BaseSession signature
    ) -> Any:
        del bot, timeout
        self.requests.append(method)
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 - required BaseSession signature
        chunk_size: int = 65_536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        del url, headers, timeout, chunk_size, raise_for_status
        if False:  # pragma: no cover - this session never streams
            yield b""


def _message(text: str, update_id: int) -> Message:
    return Message(
        message_id=update_id,
        date=datetime(2026, 9, 21, tzinfo=UTC),
        chat=Chat(id=100, type="private"),
        from_user=User(id=200, is_bot=False, first_name="Offline"),
        text=text,
        entities=(MessageEntity(type="bot_command", offset=0, length=len(text)),),
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/start", "LOCAL / CHỈ ĐỌC"),
        ("/catalog", "DANH MỤC — MOCK / CHỈ ĐỌC"),
        ("/orders", "Checkout và đơn hàng thật hiện không khả dụng"),
        ("/support", "HỖ TRỢ TĨNH / NGOẠI TUYẾN"),
    ],
)
async def test_aiogram_dispatches_commands_through_an_in_memory_session(
    command: str,
    expected: str,
) -> None:
    reader = FakeCatalogReader(FakeCatalogScenario.FRESH)
    dispatcher = build_dispatcher(reader)
    session = RecordingSession()
    bot = Bot(token="0:offline", session=session)
    update = Update(update_id=1, message=_message(command, 1))

    await dispatcher.feed_update(bot, update)

    sent = [request for request in session.requests if isinstance(request, SendMessage)]
    assert len(sent) == 1
    assert expected in sent[0].text


async def test_aiogram_dispatches_callback_and_uses_current_reader_data() -> None:
    reader = FakeCatalogReader(FakeCatalogScenario.FRESH)
    dispatcher = build_dispatcher(reader)
    session = RecordingSession()
    bot = Bot(token="0:offline", session=session)
    callback = CallbackQuery(
        id="offline-callback",
        from_user=User(id=200, is_bot=False, first_name="Offline"),
        chat_instance="offline-chat",
        message=_message("catalog result", 2),
        data=encode_quote_callback("learning-pass", "learning-pass-30d"),
    )

    await dispatcher.feed_update(bot, Update(update_id=2, callback_query=callback))

    assert any(isinstance(request, AnswerCallbackQuery) for request in session.requests)
    sent = [request for request in session.requests if isinstance(request, SendMessage)]
    assert len(sent) == 1
    assert "amount_minor=49000; currency=VND; unit=minor" in sent[0].text
    assert "BÁO GIÁ MÔ PHỎNG — MOCK / CHỈ ĐỌC" in sent[0].text


async def test_aiogram_multi_source_catalog_starts_with_an_explicit_source_menu() -> None:
    dispatcher = build_dispatcher(
        CatalogRegistry(
            {
                "khommo": FakeCatalogReader(FakeCatalogScenario.FRESH),
                "vietshare": FakeCatalogReader(FakeCatalogScenario.FRESH),
            }
        )
    )
    session = RecordingSession()
    bot = Bot(token="0:offline", session=session)

    await dispatcher.feed_update(
        bot,
        Update(update_id=3, message=_message("/catalog", 3)),
    )

    sent = [request for request in session.requests if isinstance(request, SendMessage)]
    assert len(sent) == 1
    assert "CHỌN NGUỒN DANH MỤC — CHỈ ĐỌC" in sent[0].text
    assert sent[0].reply_markup is not None
    assert [row[0].text for row in sent[0].reply_markup.inline_keyboard] == [
        "KhoMMO · CHỈ ĐỌC",
        "VietShare · CHỈ ĐỌC",
    ]


async def test_hard_network_guard_covers_all_offline_flows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("outbound socket, DNS, or HTTP access attempted")

    async def forbidden_async(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("HTTP or Telegram transport attempted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden_async)
    monkeypatch.setattr(Bot, "__call__", forbidden_async)

    reader = FakeCatalogReader(FakeCatalogScenario.FRESH)
    build_dispatcher(reader)
    start_message = FakeMessage()
    catalog_message = FakeMessage()
    orders_message = FakeMessage()
    support_message = FakeMessage()
    quote_message = FakeMessage()

    await start_handler(start_message)
    await catalog_handler(catalog_message, reader)
    await orders_handler(orders_message)
    await support_handler(support_message)
    await callback_handler(
        FakeCallback(
            encode_quote_callback("learning-pass", "learning-pass-30d"),
            quote_message,
        ),
        reader,
    )

    assert "LOCAL / CHỈ ĐỌC" in start_message.text
    assert "DANH MỤC" in catalog_message.text
    assert "ĐƠN HÀNG" in orders_message.text
    assert "HỖ TRỢ" in support_message.text
    assert "BÁO GIÁ MÔ PHỎNG" in quote_message.text
