"""Small, fail-closed callback codec for the read-only catalog bot."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

TELEGRAM_CALLBACK_DATA_MAX_BYTES: Final = 64
CALLBACK_VERSION: Final = "1"
CALLBACK_SEPARATOR: Final = ":"

# The longest quote callback is ``1:q:<product>:<variant>``. Two identifiers at
# this limit produce 63 ASCII bytes, leaving the Telegram 64-byte boundary intact.
MAX_CALLBACK_IDENTIFIER_BYTES: Final = 29
_IDENTIFIER_PATTERN: Final = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._-]{{0,{MAX_CALLBACK_IDENTIFIER_BYTES - 1}}}",
    flags=re.ASCII,
)


class CallbackCodecError(ValueError):
    """Raised when untrusted callback data is not canonical and safe."""


class CallbackAction(StrEnum):
    """Actions supported by the version-one bot callback format."""

    DETAIL = "d"
    QUOTE = "q"


@dataclass(frozen=True, slots=True)
class CatalogCallback:
    """A decoded callback containing normalized identities only."""

    action: CallbackAction
    product_id: str
    variant_id: str | None = None
    version: str = CALLBACK_VERSION


def _validated_identifier(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CallbackCodecError("callback identifier must be a non-empty string")
    if not value.isascii():
        raise CallbackCodecError("callback identifier must be ASCII")
    if len(value.encode("ascii")) > MAX_CALLBACK_IDENTIFIER_BYTES:
        raise CallbackCodecError("callback identifier is too long")
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise CallbackCodecError("callback identifier is not canonical")
    return value


def encode_callback(
    action: CallbackAction | str,
    product_id: str,
    variant_id: str | None = None,
) -> str:
    """Encode one canonical callback and enforce Telegram's byte limit."""
    try:
        parsed_action = CallbackAction(action)
    except (TypeError, ValueError) as exc:
        raise CallbackCodecError("unknown callback action") from exc

    normalized_product_id = _validated_identifier(product_id)
    parts: tuple[str, ...]
    if parsed_action is CallbackAction.DETAIL:
        if variant_id is not None:
            raise CallbackCodecError("detail callback cannot contain a variant")
        parts = (CALLBACK_VERSION, parsed_action.value, normalized_product_id)
    else:
        normalized_variant_id = _validated_identifier(variant_id)
        parts = (
            CALLBACK_VERSION,
            parsed_action.value,
            normalized_product_id,
            normalized_variant_id,
        )

    encoded = CALLBACK_SEPARATOR.join(parts)
    if len(encoded.encode("ascii")) > TELEGRAM_CALLBACK_DATA_MAX_BYTES:
        raise CallbackCodecError("callback data exceeds Telegram's byte limit")
    return encoded


def encode_detail_callback(product_id: str) -> str:
    """Encode a product-detail callback."""
    return encode_callback(CallbackAction.DETAIL, product_id)


def encode_quote_callback(product_id: str, variant_id: str) -> str:
    """Encode a simulated-quote callback."""
    return encode_callback(CallbackAction.QUOTE, product_id, variant_id)


def decode_callback(data: object) -> CatalogCallback:
    """Decode untrusted callback data, rejecting every non-canonical form."""
    if not isinstance(data, str) or not data:
        raise CallbackCodecError("callback data must be a non-empty string")
    if not data.isascii():
        raise CallbackCodecError("callback data must be ASCII")
    if len(data.encode("ascii")) > TELEGRAM_CALLBACK_DATA_MAX_BYTES:
        raise CallbackCodecError("callback data exceeds Telegram's byte limit")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in data):
        raise CallbackCodecError("callback data contains a control character")

    parts = data.split(CALLBACK_SEPARATOR)
    if not parts or parts[0] != CALLBACK_VERSION:
        raise CallbackCodecError("unknown callback version")
    if len(parts) < 2:
        raise CallbackCodecError("callback action is missing")

    try:
        action = CallbackAction(parts[1])
    except ValueError as exc:
        raise CallbackCodecError("unknown callback action") from exc

    expected_parts = 3 if action is CallbackAction.DETAIL else 4
    if len(parts) != expected_parts:
        raise CallbackCodecError("callback field count is invalid")

    product_id = _validated_identifier(parts[2])
    variant_id = _validated_identifier(parts[3]) if action is CallbackAction.QUOTE else None
    canonical = encode_callback(action, product_id, variant_id)
    if canonical != data:
        raise CallbackCodecError("callback data is not canonical")
    return CatalogCallback(action=action, product_id=product_id, variant_id=variant_id)
