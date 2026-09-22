"""Offline aiogram handler tests."""

from nyan_shop_bot.bot.handlers import build_dispatcher, start_handler


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str) -> object:
        self.answers.append(text)
        return object()


async def test_start_handler_is_offline_and_honest() -> None:
    message = FakeMessage()

    await start_handler(message)

    assert len(message.answers) == 1
    assert "LOCAL / CHỈ ĐỌC" in message.answers[0]
    assert "vô hiệu hóa" in message.answers[0]


def test_dispatcher_has_foundation_router_without_transport() -> None:
    dispatcher = build_dispatcher()

    assert dispatcher.sub_routers
    assert dispatcher.sub_routers[0].name == "foundation"
