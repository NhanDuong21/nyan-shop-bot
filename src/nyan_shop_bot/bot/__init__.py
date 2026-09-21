"""Offline-testable, read-only Telegram catalog experience."""

from nyan_shop_bot.bot.callbacks import (
    CALLBACK_VERSION,
    MAX_CALLBACK_IDENTIFIER_BYTES,
    TELEGRAM_CALLBACK_DATA_MAX_BYTES,
    CallbackAction,
    CallbackCodecError,
    CatalogCallback,
    decode_callback,
    encode_callback,
    encode_detail_callback,
    encode_quote_callback,
)
from nyan_shop_bot.bot.handlers import build_dispatcher, build_router

__all__ = [
    "CALLBACK_VERSION",
    "MAX_CALLBACK_IDENTIFIER_BYTES",
    "TELEGRAM_CALLBACK_DATA_MAX_BYTES",
    "CallbackAction",
    "CallbackCodecError",
    "CatalogCallback",
    "build_dispatcher",
    "build_router",
    "decode_callback",
    "encode_callback",
    "encode_detail_callback",
    "encode_quote_callback",
]
