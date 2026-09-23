"""The owner-started Telegram runtime remains explicit, local, and offline in tests."""

from __future__ import annotations

import pytest

from nyan_shop_bot.bot import runtime
from nyan_shop_bot.config import Settings


def _live_settings(
    *,
    telegram_token: str | None = "0:synthetic-telegram",
    use_vietshare: bool = False,
) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="local",
        app_host="127.0.0.1",
        supplier_mode="vietshare-readonly" if use_vietshare else "khommo-readonly",
        khommo_api_token=None if use_vietshare else "synthetic-khommo",
        vietshare_api_id="synthetic-vietshare-id" if use_vietshare else None,
        vietshare_api_secret="synthetic-vietshare-secret" if use_vietshare else None,
        telegram_bot_token=telegram_token,
        payment_mode="disabled",
        allow_real_purchases=False,
    )


async def test_polling_requires_explicit_owner_confirmation() -> None:
    with pytest.raises(
        runtime.TelegramRuntimeConfigurationError,
        match="explicit --start-local-polling flag",
    ):
        await runtime.run_local_polling(
            settings=_live_settings(),
            owner_confirmed=False,
        )


async def test_polling_requires_local_telegram_token_without_echoing_other_secrets() -> None:
    with pytest.raises(
        runtime.TelegramRuntimeConfigurationError,
        match="Set TELEGRAM_BOT_TOKEN only in the ignored local .env file",
    ) as captured:
        await runtime.run_local_polling(
            settings=_live_settings(telegram_token=None),
            owner_confirmed=True,
        )

    assert "synthetic-khommo" not in str(captured.value)


async def test_polling_rejects_mock_catalog_for_the_real_read_slice() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supplier_mode="mock",
        telegram_bot_token="0:synthetic-telegram",
    )

    with pytest.raises(
        runtime.TelegramRuntimeConfigurationError,
        match="explicit read-only supplier mode",
    ):
        await runtime.run_local_polling(settings=settings, owner_confirmed=True)


@pytest.mark.parametrize("use_vietshare", [False, True])
async def test_confirmed_runtime_injects_catalog_and_closes_every_session(
    monkeypatch: pytest.MonkeyPatch,
    use_vietshare: bool,
) -> None:
    events: list[object] = []
    reader = object()

    class FakeSession:
        async def close(self) -> None:
            events.append("bot-closed")

    class FakeBot:
        def __init__(self, *, token: str) -> None:
            events.append(("bot-created", token))
            self.session = FakeSession()

    class FakeDispatcher:
        def resolve_used_update_types(self) -> list[str]:
            return ["message", "callback_query"]

        async def start_polling(self, bot: object, **kwargs: object) -> None:
            events.append(("polling", bot, kwargs))

    async def close_catalog() -> None:
        events.append("catalog-closed")

    dispatcher = FakeDispatcher()
    monkeypatch.setattr(runtime, "Bot", FakeBot)
    monkeypatch.setattr(runtime, "build_catalog_reader", lambda settings: (reader, close_catalog))
    monkeypatch.setattr(
        runtime,
        "build_dispatcher",
        lambda received_reader: dispatcher if received_reader is reader else None,
    )

    await runtime.run_local_polling(
        settings=_live_settings(use_vietshare=use_vietshare),
        owner_confirmed=True,
    )

    polling = next(event for event in events if isinstance(event, tuple) and event[0] == "polling")
    assert polling[2] == {
        "allowed_updates": ["message", "callback_query"],
        "close_bot_session": False,
    }
    assert events[-2:] == ["catalog-closed", "bot-closed"]
