"""Callback data stays compact, identity-only, and fail-closed."""

import pytest

from nyan_shop_bot.bot.callbacks import (
    MAX_CALLBACK_IDENTIFIER_BYTES,
    TELEGRAM_CALLBACK_DATA_MAX_BYTES,
    CallbackAction,
    CallbackCodecError,
    decode_callback,
    encode_callback,
    encode_detail_callback,
    encode_quote_callback,
)


def test_detail_and_quote_callbacks_round_trip_at_the_size_boundary() -> None:
    product_id = "p" * MAX_CALLBACK_IDENTIFIER_BYTES
    variant_id = "v" * MAX_CALLBACK_IDENTIFIER_BYTES

    detail = encode_detail_callback(product_id)
    quote = encode_quote_callback(product_id, variant_id)

    assert decode_callback(detail).action is CallbackAction.DETAIL
    assert decode_callback(detail).product_id == product_id
    decoded_quote = decode_callback(quote)
    assert decoded_quote.action is CallbackAction.QUOTE
    assert decoded_quote.product_id == product_id
    assert decoded_quote.variant_id == variant_id
    assert len(detail.encode("ascii")) <= TELEGRAM_CALLBACK_DATA_MAX_BYTES
    assert len(quote.encode("ascii")) <= TELEGRAM_CALLBACK_DATA_MAX_BYTES


def test_callback_contains_only_version_action_and_normalized_ids() -> None:
    callback_data = encode_quote_callback("product-1", "variant_2")

    assert callback_data == "1:q:product-1:variant_2"
    for client_field in ("title", "description", "price", "currency", "quantity", "supplier"):
        assert client_field not in callback_data


@pytest.mark.parametrize(
    "payload",
    [
        None,
        123,
        "",
        "2:d:product",
        "v1:d:product",
        "1",
        "1::product",
        "1:x:product",
        "1:d:",
        "1:q:product:",
        "1:q::variant",
        "1:q:product",
        "1:d:product:smuggled",
        "1:q:product:variant:smuggled",
        "1:d:product:variant:price:999:currency:USD",
        "1:d:café",
        "1:d:product\nforged",
        "1:d:product\x7f",
        "1:d:contains space",
        "1:d:-leading-separator",
        f"1:d:{'p' * (MAX_CALLBACK_IDENTIFIER_BYTES + 1)}",
        "x" * (TELEGRAM_CALLBACK_DATA_MAX_BYTES + 1),
    ],
)
def test_decode_rejects_malformed_unknown_smuggled_and_overlong_data(payload: object) -> None:
    with pytest.raises(CallbackCodecError):
        decode_callback(payload)


@pytest.mark.parametrize(
    ("action", "product_id", "variant_id"),
    [
        ("unknown", "product", None),
        (CallbackAction.DETAIL, "", None),
        (CallbackAction.DETAIL, "product", "unexpected"),
        (CallbackAction.QUOTE, "product", None),
        (CallbackAction.QUOTE, "product", "variant:smuggled"),
        (CallbackAction.QUOTE, "product", "biến-thể"),
    ],
)
def test_encode_rejects_noncanonical_fields(
    action: CallbackAction | str,
    product_id: str,
    variant_id: str | None,
) -> None:
    with pytest.raises(CallbackCodecError):
        encode_callback(action, product_id, variant_id)
