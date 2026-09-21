"""Offline schema and monetary-boundary tests for Roboticvn v2 responses."""

from __future__ import annotations

import json
from dataclasses import fields
from typing import Any

import pytest

from nyan_shop_bot.suppliers.roboticvn import (
    ABSENT,
    MonetaryProjectionGap,
    Product,
    UnsupportedMonetaryProjection,
    UnsupportedSchemaError,
    WalletTransactionReason,
    WalletTransactionType,
    parse_product_detail,
    parse_product_list,
    parse_wallet_balance,
    parse_wallet_transactions,
)


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def meta(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {"count": 1, "limit": 20, "offset": 0}
    value.update(changes)
    return value


def variant(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "variant-synthetic-1",
        "title": "Synthetic variant",
        "prices": {"vnd": 25_000, "usd": 2},
        "in_stock": True,
        "available_quantity": 4,
    }
    value.update(changes)
    return value


def product(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "product-synthetic-1",
        "title": "Synthetic product",
        "description": None,
        "thumbnail": None,
        "in_stock": True,
        "variants": [variant()],
    }
    value.update(changes)
    return value


def transaction(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "type": "debit",
        "reason": "purchase",
        "description": "Synthetic offline transaction",
        "amount": 25_000,
        "currency_code": "vnd",
        "created_at": "2026-09-21T03:05:06Z",
    }
    value.update(changes)
    return value


def test_product_list_requires_data_and_meta_but_accepts_documented_extensions() -> None:
    result = parse_product_list(
        encoded(
            {
                "data": [{"id": "product-synthetic-1", "title": "Synthetic product"}],
                "meta": {**meta(), "future_meta": {"opaque": True}},
                "future_envelope": ["ignored"],
            }
        )
    )

    assert result.data[0].id == "product-synthetic-1"
    assert result.data[0].title == "Synthetic product"
    assert (result.meta.count, result.meta.limit, result.meta.offset) == (1, 20, 0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"meta": meta()},
        {"data": {}, "meta": meta()},
        {"data": [], "meta": []},
        {"data": [], "meta": {"limit": 20, "offset": 0}},
        {"data": [], "meta": {"count": True, "limit": 20, "offset": 0}},
        {"data": [], "meta": {"count": 0, "limit": 20.0, "offset": 0}},
    ],
)
def test_product_list_rejects_missing_or_malformed_envelope_members(payload: object) -> None:
    with pytest.raises(UnsupportedSchemaError):
        parse_product_list(encoded(payload))


@pytest.mark.parametrize(
    "summary",
    [
        {},
        {"id": "only-id"},
        {"title": "only-title"},
        {"id": 1, "title": "title"},
        {"id": "id", "title": None},
        {"id": "id", "title": "title", "extra": "forbidden"},
    ],
)
def test_product_summary_requires_exact_documented_fields(summary: object) -> None:
    with pytest.raises(UnsupportedSchemaError):
        parse_product_list(encoded({"data": [summary], "meta": meta()}))


def test_product_declares_no_required_fields_and_preserves_absence() -> None:
    parsed = parse_product_detail(encoded({"data": {}, "future_envelope": True}))

    assert parsed == Product()
    assert parsed.id is ABSENT
    assert parsed.title is ABSENT
    assert parsed.description is ABSENT
    assert parsed.thumbnail is ABSENT
    assert parsed.in_stock is ABSENT
    assert parsed.variants is ABSENT


def test_product_nullable_fields_are_distinct_from_absent_fields() -> None:
    parsed = parse_product_detail(encoded({"data": {"description": None, "thumbnail": None}}))

    assert parsed.description is None
    assert parsed.thumbnail is None
    assert parsed.id is ABSENT


@pytest.mark.parametrize(
    "changed",
    [
        {"unknown": "forbidden"},
        {"id": 1},
        {"title": False},
        {"description": 1},
        {"thumbnail": []},
        {"in_stock": 1},
        {"variants": {}},
    ],
)
def test_product_rejects_only_its_explicitly_forbidden_extras_and_wrong_types(
    changed: dict[str, object],
) -> None:
    with pytest.raises(UnsupportedSchemaError):
        parse_product_detail(encoded({"data": changed}))


def test_variant_identity_stock_and_optional_fields_are_preserved_separately() -> None:
    parsed = parse_product_detail(
        encoded(
            {
                "data": product(
                    variants=[
                        variant(
                            description=None,
                            delivery_instructions="Synthetic instruction",
                            reseller_notes=None,
                        )
                    ]
                ),
                "future_envelope": "accepted",
            }
        )
    )

    assert parsed.id == "product-synthetic-1"
    assert isinstance(parsed.variants, tuple)
    item = parsed.variants[0]
    assert item.id == "variant-synthetic-1"
    assert item.id != parsed.id
    assert item.in_stock is True
    assert item.available_quantity == 4
    assert item.description is None
    assert item.delivery_instructions == "Synthetic instruction"
    assert item.reseller_notes is None


@pytest.mark.parametrize(
    "changed",
    [
        {"id": None},
        {"title": 1},
        {"prices": []},
        {"prices": {"vnd": True}},
        {"prices": {"vnd": "25000"}},
        {"in_stock": 1},
        {"available_quantity": True},
        {"available_quantity": 1.5},
        {"unexpected": "forbidden"},
    ],
)
def test_variant_rejects_wrong_types_booleans_as_integers_and_additional_properties(
    changed: dict[str, object],
) -> None:
    with pytest.raises(UnsupportedSchemaError):
        parse_product_detail(encoded({"data": product(variants=[variant(**changed)])}))


@pytest.mark.parametrize(
    "missing",
    ["id", "title", "prices", "in_stock", "available_quantity"],
)
def test_variant_requires_all_documented_identity_price_and_stock_fields(missing: str) -> None:
    item = variant()
    del item[missing]
    with pytest.raises(UnsupportedSchemaError):
        parse_product_detail(encoded({"data": product(variants=[item])}))


def test_variant_decimal_prices_become_typed_gap_without_amount_or_float() -> None:
    parsed = parse_product_detail(
        b'{"data":{"variants":[{"id":"v-1","title":"Synthetic",'
        b'"prices":{"vnd":1250.75,"usd":0.99},"in_stock":true,'
        b'"available_quantity":2}]}}'
    )

    assert isinstance(parsed.variants, tuple)
    projection = parsed.variants[0].prices
    assert projection == UnsupportedMonetaryProjection(currency_codes=("vnd", "usd"))
    assert projection.reason is MonetaryProjectionGap.UNIT_AND_SCALE_UNDOCUMENTED
    assert projection.status == "unsupported"
    assert projection.retryable is False
    assert {item.name for item in fields(projection)} == {
        "currency_codes",
        "reason",
        "status",
        "retryable",
    }
    assert not hasattr(projection, "amount")
    assert not hasattr(projection, "amount_minor")


def test_wallet_balance_accepts_extensions_and_fails_closed_on_all_numeric_values() -> None:
    result = parse_wallet_balance(b'{"data":{"vnd":125000.50,"usd":2},"future_envelope":"ignored"}')

    projection = result.monetary_projection
    assert projection.currency_codes == ("vnd", "usd")
    assert projection.reason is MonetaryProjectionGap.UNIT_AND_SCALE_UNDOCUMENTED
    assert not hasattr(projection, "amount")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": {"vnd": True}},
        {"data": {"vnd": "125000"}},
        {"data": {"vnd": None}},
    ],
)
def test_wallet_balance_validates_required_envelope_and_numeric_map(payload: object) -> None:
    with pytest.raises(UnsupportedSchemaError):
        parse_wallet_balance(encoded(payload))


def test_invalid_currency_value_error_does_not_echo_response_derived_key() -> None:
    private_key = "supplier-private-currency-key"
    with pytest.raises(UnsupportedSchemaError) as caught:
        parse_wallet_balance(encoded({"data": {private_key: "not-a-number"}}))
    assert private_key not in str(caught.value)
    assert private_key not in repr(caught.value)


def test_wallet_balance_allows_no_required_currency() -> None:
    parsed = parse_wallet_balance(encoded({"data": {}}))
    assert parsed.monetary_projection.currency_codes == ()


def test_wallet_transactions_preserve_non_money_fields_and_discard_amount() -> None:
    parsed = parse_wallet_transactions(
        b'{"data":[{"type":"debit","reason":"purchase",'
        b'"description":"Synthetic transaction","amount":1250.75,'
        b'"currency_code":"vnd","created_at":"2026-09-21T03:05:06+07:00"}],'
        b'"meta":{"count":1,"limit":20,"offset":0,"future":true},'
        b'"future_envelope":true}'
    )

    item = parsed.data[0]
    assert item.type is WalletTransactionType.DEBIT
    assert item.reason is WalletTransactionReason.PURCHASE
    assert item.description == "Synthetic transaction"
    assert item.currency_code == "vnd"
    assert item.created_at == "2026-09-21T03:05:06+07:00"
    assert isinstance(item.amount, UnsupportedMonetaryProjection)
    assert item.amount.currency_codes == ("vnd",)
    assert not hasattr(item.amount, "amount")


@pytest.mark.parametrize(
    "created_at",
    [
        "2026-09-21t03:05:06z",
        "2026-09-21t03:05:06.125+07:00",
    ],
)
def test_wallet_transaction_accepts_lowercase_rfc3339_markers_and_preserves_source(
    created_at: str,
) -> None:
    parsed = parse_wallet_transactions(
        encoded({"data": [transaction(created_at=created_at)], "meta": meta()})
    )

    assert parsed.data[0].created_at == created_at


def test_wallet_transaction_declares_no_required_fields() -> None:
    parsed = parse_wallet_transactions(encoded({"data": [{}], "meta": meta()}))
    item = parsed.data[0]

    assert item.type is ABSENT
    assert item.reason is ABSENT
    assert item.description is ABSENT
    assert item.amount is ABSENT
    assert item.currency_code is ABSENT
    assert item.created_at is ABSENT


@pytest.mark.parametrize(
    "changed",
    [
        {"type": "other"},
        {"type": 1},
        {"reason": "deposit"},
        {"reason": None},
        {"description": None},
        {"amount": True},
        {"amount": "1"},
        {"currency_code": 1},
        {"created_at": "2026-09-21"},
        {"created_at": "2026-09-21 03:05:06Z"},
        {"created_at": "2026-09-21t24:00:00z"},
        {"created_at": "2026-09-21t03:60:00z"},
        {"created_at": "2026-09-21t03:05:60z"},
        {"unexpected": "forbidden"},
    ],
)
def test_wallet_transaction_rejects_invalid_documented_fields_and_extras(
    changed: dict[str, object],
) -> None:
    with pytest.raises(UnsupportedSchemaError):
        parse_wallet_transactions(encoded({"data": [changed], "meta": meta()}))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"meta": meta()},
        {"data": {}, "meta": meta()},
        {"data": [], "meta": {"count": 0, "limit": 20}},
    ],
)
def test_wallet_transactions_require_data_and_meta(payload: object) -> None:
    with pytest.raises(UnsupportedSchemaError):
        parse_wallet_transactions(encoded(payload))


@pytest.mark.parametrize(
    "raw_body",
    [
        b"not-json-private-body",
        b'{"data":{},"data":{}}',
        b'{"data":{"vnd":NaN}}',
        b"\xff\xfe",
    ],
)
def test_response_parse_errors_never_echo_raw_body(raw_body: bytes) -> None:
    parsers: tuple[Any, ...] = (
        parse_product_list,
        parse_product_detail,
        parse_wallet_balance,
        parse_wallet_transactions,
    )
    for parser in parsers:
        with pytest.raises(ValueError) as caught:
            parser(raw_body)
        decoded = raw_body.decode("utf-8", errors="ignore")
        if decoded:
            assert decoded not in str(caught.value)
            assert decoded not in repr(caught.value)


def test_response_derived_representations_are_redacted() -> None:
    secret = "supplier-response-private-marker"
    values = (
        parse_product_list(encoded({"data": [{"id": secret, "title": secret}], "meta": meta()})),
        parse_product_detail(
            encoded({"data": product(id=secret, title=secret, variants=[variant(id=secret)])})
        ),
        parse_wallet_transactions(
            encoded({"data": [transaction(description=secret)], "meta": meta()})
        ),
    )

    representations = " ".join(
        [repr(value) for value in values]
        + [repr(values[0].data[0])]
        + [repr(values[1].variants[0])]  # type: ignore[index,union-attr]
        + [repr(values[2].data[0])]
    )
    assert secret not in representations
    assert "25000" not in representations
