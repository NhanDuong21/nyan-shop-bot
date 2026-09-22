"""Explicit owner-started local polling runtime for the read-only Telegram bot."""

from __future__ import annotations

import argparse
import asyncio
import sys

from aiogram import Bot

from nyan_shop_bot.bot.handlers import build_dispatcher
from nyan_shop_bot.catalog.factory import build_catalog_reader
from nyan_shop_bot.config import Settings, is_loopback_host


class TelegramRuntimeConfigurationError(ValueError):
    """The local Telegram transport was not explicitly and safely configured."""


async def run_local_polling(
    *,
    settings: Settings,
    owner_confirmed: bool,
) -> None:
    """Start polling only after an explicit command-line owner confirmation."""
    if not owner_confirmed:
        raise TelegramRuntimeConfigurationError(
            "Telegram polling requires the explicit --start-local-polling flag"
        )
    if settings.app_env != "local" or not is_loopback_host(settings.app_host):
        raise TelegramRuntimeConfigurationError(
            "Telegram polling is allowed only with a loopback local application runtime"
        )
    if settings.supplier_mode != "khommo-readonly":
        raise TelegramRuntimeConfigurationError(
            "This product slice requires SUPPLIER_MODE=khommo-readonly"
        )

    token = settings.telegram_bot_token
    if token is None or not token.get_secret_value():
        raise TelegramRuntimeConfigurationError(
            "Set TELEGRAM_BOT_TOKEN only in the ignored local .env file"
        )

    bot = Bot(token=token.get_secret_value())
    close_catalog = None
    try:
        catalog, close_catalog = build_catalog_reader(settings)
        dispatcher = build_dispatcher(catalog)
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
        )
    finally:
        try:
            if close_catalog is not None:
                await close_catalog()
        finally:
            await bot.session.close()


def main(argv: list[str] | None = None) -> int:
    """Parse the deliberate owner action without ever echoing configuration values."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-local-polling",
        action="store_true",
        help="confirm that the owner intends to contact Telegram from this local process",
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings()
        asyncio.run(
            run_local_polling(
                settings=settings,
                owner_confirmed=args.start_local_polling,
            )
        )
    except TelegramRuntimeConfigurationError as error:
        print(f"Telegram runtime not started: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("Telegram runtime stopped without exposing private configuration.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
