"""Verify the sanitized Roboticvn source record without fetching either source."""

from __future__ import annotations

import re
from pathlib import Path

from nyan_shop_bot.suppliers.roboticvn import (
    API_PREFIX,
    AUTHORIZED_READ_PATHS,
    GLOBAL_AUTH_HEADER,
    PASTED_SWAGGER_SHA256,
    PRODUCTION_ORIGIN,
    PUBLIC_API_TITLE,
    PUBLIC_API_VERSION,
    PUBLIC_FETCH_CONTENT_TYPE,
    PUBLIC_FETCH_HTTP_STATUS,
    PUBLIC_FETCH_RAW_BYTES,
    PUBLIC_FETCHED_AT,
    PUBLIC_OPENAPI_SHA256,
    PUBLIC_OPENAPI_SPEC_VERSION,
    PUBLIC_OPENAPI_URL,
)

ROOT = Path(__file__).resolve().parents[3]
NOTE = ROOT / "docs" / "provenance" / "roboticvn-v2.md"


def test_machine_readable_provenance_constants_match_sanitized_checks() -> None:
    assert PRODUCTION_ORIGIN == "https://api.roboticvn.com"
    assert API_PREFIX == "/api/v2"
    assert GLOBAL_AUTH_HEADER == "x-api-key"
    assert PASTED_SWAGGER_SHA256 == (
        "09be6d7dd099c57115ecd611d67bc0a28b0dcb12634b7435051d98e20db0cc9f"
    )
    assert PUBLIC_OPENAPI_URL == "https://api.roboticvn.com/api/v2/docs/openapi.json"
    assert PUBLIC_OPENAPI_SHA256 == (
        "22de68f114b6c30e68cc88ded579bf4b77632f43bc67fe9c74bbe60f8cdb1930"
    )
    assert PUBLIC_FETCHED_AT == "2026-09-21T03:05:06Z"
    assert PUBLIC_FETCH_HTTP_STATUS == 200
    assert PUBLIC_FETCH_CONTENT_TYPE == "application/json"
    assert PUBLIC_FETCH_RAW_BYTES == 19_482
    assert PUBLIC_OPENAPI_SPEC_VERSION == "3.0.3"
    assert PUBLIC_API_TITLE == "Roboticvn Customer API"
    assert PUBLIC_API_VERSION == "2.2.0"


def test_authorized_read_paths_are_exact_and_all_use_v2_prefix() -> None:
    assert AUTHORIZED_READ_PATHS == (
        "/api/v2/products",
        "/api/v2/products/{id}",
        "/api/v2/wallet/balance",
        "/api/v2/wallet/transactions",
    )
    assert all(path.startswith(API_PREFIX + "/") for path in AUTHORIZED_READ_PATHS)


def test_provenance_note_contains_only_sanitized_boundary_and_audit_facts() -> None:
    text = NOTE.read_text(encoding="utf-8")

    for expected in (
        PASTED_SWAGGER_SHA256,
        PUBLIC_OPENAPI_SHA256,
        PUBLIC_FETCHED_AT,
        PUBLIC_OPENAPI_URL,
        PUBLIC_FETCH_CONTENT_TYPE,
        PUBLIC_OPENAPI_SPEC_VERSION,
        PUBLIC_API_TITLE,
        PUBLIC_API_VERSION,
        *AUTHORIZED_READ_PATHS,
        "ProductQuoteRequest",
        "CreateOrderRequest",
        "TopupRequest",
        "unit",
        "scale",
        "Retry-After",
    ):
        assert expected in text

    assert "19,482" in text
    assert "HTTP `200`" in text
    assert "required" in text
    assert "idempotency" in text
    assert "uncertain-outcome reconciliation" in text
    assert "supplier-obligation" in text
    assert "settlement" in text
    assert "delivery-credential safety" in text
    assert "remain disabled" in text
    assert "```" not in text
    assert '"properties"' not in text
    assert '"example"' not in text
    assert len(re.findall(r"\b[0-9a-f]{64}\b", text)) == 2
