"""Strict parsing tests for the only documented VietShare response schema."""

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from nyan_shop_bot.suppliers.vietshare import (
    ResponseValidationError,
    VietShareProductList,
    VietShareResponse,
    parse_product_list,
)


def product_fixture() -> dict[str, Any]:
    return {
        "count": 2,
        "products": [
            {
                "id": 101,
                "name": "Synthetic access A",
                "description": "Fixture-only product; it is not a supplier offer.",
                "price": 49_000,
                "flash_sale_id": None,
                "stock": 12,
                "allow_quantity": True,
                "max_quantity": 3,
            },
            {
                "id": 202,
                "name": "Synthetic access B",
                "description": "Another offline-only fixture.",
                "price": 0,
                "flash_sale_id": 7,
                "stock": 0,
                "allow_quantity": False,
                "max_quantity": 1,
            },
        ],
    }


def encoded_fixture(value: object | None = None) -> bytes:
    payload = product_fixture() if value is None else value
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_product_list_parses_only_documented_fields_with_explicit_vnd_money() -> None:
    result = parse_product_list(encoded_fixture())

    assert isinstance(result, VietShareProductList)
    assert result.count == 2
    assert tuple(product.id for product in result.products) == (101, 202)
    first = result.products[0]
    assert first.name == "Synthetic access A"
    assert first.description == "Fixture-only product; it is not a supplier offer."
    assert first.price.amount_minor == 49_000
    assert first.price.currency == "VND"
    assert first.price.unit == "minor"
    assert first.price_vnd == 49_000
    assert first.stock == 12
    assert first.allow_quantity is True
    assert first.max_quantity == 3
    assert first.flash_sale_id is None


def _set_product_field(name: str, value: object) -> Callable[[dict[str, Any]], None]:
    def mutate(payload: dict[str, Any]) -> None:
        payload["products"][0][name] = value

    return mutate


def _remove_product_field(name: str) -> Callable[[dict[str, Any]], None]:
    def mutate(payload: dict[str, Any]) -> None:
        del payload["products"][0][name]

    return mutate


def _add_unknown_product_field(payload: dict[str, Any]) -> None:
    payload["products"][0]["undocumented-sensitive-field"] = "must-not-leak"


def _add_unknown_top_level_field(payload: dict[str, Any]) -> None:
    payload["cursor"] = "invented-pagination-token"


@pytest.mark.parametrize(
    "mutate",
    [
        _set_product_field("id", True),
        _set_product_field("id", "101"),
        _set_product_field("name", 1),
        _set_product_field("description", None),
        _set_product_field("price", -1),
        _set_product_field("price", 1.5),
        _set_product_field("price", True),
        _set_product_field("flash_sale_id", "7"),
        _set_product_field("flash_sale_id", False),
        _set_product_field("stock", -1),
        _set_product_field("stock", 2.5),
        _set_product_field("stock", False),
        _set_product_field("allow_quantity", 1),
        _set_product_field("max_quantity", 0),
        _set_product_field("max_quantity", 1.5),
        _set_product_field("max_quantity", True),
        _remove_product_field("description"),
        _add_unknown_product_field,
        _add_unknown_top_level_field,
    ],
)
def test_product_list_rejects_unknown_or_malformed_fields(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    payload = deepcopy(product_fixture())
    mutate(payload)

    with pytest.raises(ResponseValidationError):
        parse_product_list(encoded_fixture(payload))


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"count": 0, "products": {}},
        {"count": True, "products": []},
        {"count": -1, "products": []},
        {"count": 2, "products": []},
        {"products": []},
        {"count": 0},
    ],
)
def test_product_list_rejects_malformed_envelopes(payload: object) -> None:
    with pytest.raises(ResponseValidationError):
        parse_product_list(encoded_fixture(payload))


@pytest.mark.parametrize(
    "raw_body",
    [
        b"not-json-sensitive-marker",
        b'{"count":0,"count":0,"products":[]}',
        b'{"count":' + (b"9" * 5_000) + b',"products":[]}',
        b"\xff\xfe\x00",
    ],
)
def test_parser_errors_never_include_raw_response_content(raw_body: bytes) -> None:
    with pytest.raises(ResponseValidationError) as caught:
        parse_product_list(raw_body)

    assert raw_body.decode("utf-8", errors="ignore") not in str(caught.value)
    assert raw_body.decode("utf-8", errors="ignore") not in repr(caught.value)


def test_response_and_parsed_model_reprs_hide_sensitive_response_content() -> None:
    sensitive_name = "supplier-response-name-must-not-print"
    payload = product_fixture()
    payload["products"][0]["name"] = sensitive_name
    body = encoded_fixture(payload)
    response = VietShareResponse(
        status_code=200,
        headers={"Authorization": "response-auth-must-not-print"},
        body=body,
    )
    parsed = parse_product_list(body)

    combined = " ".join(
        (
            repr(response),
            repr(response.headers),
            repr(parsed),
            repr(parsed.products[0]),
            repr(parsed.products[0].price),
        )
    )
    assert sensitive_name not in combined
    assert "response-auth-must-not-print" not in combined
    assert "Fixture-only product" not in combined
    assert "49000" not in combined
    assert "<redacted>" in combined


def test_parser_requires_exact_bytes_instead_of_serializing_objects() -> None:
    with pytest.raises(ResponseValidationError, match="exact response bytes"):
        parse_product_list(product_fixture())  # type: ignore[arg-type]
