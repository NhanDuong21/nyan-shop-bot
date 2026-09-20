"""Aiogram handlers without polling, webhook, or live Telegram transport."""

from typing import Protocol

from aiogram import Dispatcher, Router
from aiogram.filters import CommandStart


class AnswerableMessage(Protocol):
    """Narrow message boundary that is easy to exercise offline."""

    async def answer(self, text: str) -> object: ...


async def start_handler(message: AnswerableMessage) -> None:
    """Explain the honest Phase 0 state to a Telegram user."""
    await message.answer(
        "Nyan Shop Bot đang chạy ở chế độ MOCK. Thanh toán và mua hàng thật hiện bị vô hiệu hóa."
    )


def build_router() -> Router:
    router = Router(name="foundation")
    router.message(CommandStart())(start_handler)
    return router


def build_dispatcher() -> Dispatcher:
    """Build the dispatcher only; callers must explicitly choose a transport later."""
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    return dispatcher
