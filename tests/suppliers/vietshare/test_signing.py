"""Deterministic VietShare request-target and signing tests."""

import re

import pytest

from nyan_shop_bot.suppliers.vietshare import (
    PRODUCTION_BASE_URL,
    VietShareConfigurationError,
    VietShareCredentials,
    body_sha256,
    build_request_target,
    build_signed_read_request,
    canonical_string,
    sign_request,
)


def test_deterministic_hmac_sha256_vector_uses_exact_canonical_string() -> None:
    raw_body = b'{"z":1, "a":2}\n'
    expected_body_hash = "38c6fe0c8e342bc669f3193a11fbf65b20e0fc2b04c87c2b10ca86087c1758fd"
    expected_canonical = (
        "1760000000|fixed-nonce-1234|GET|"
        "/v1/products?category=alpha%20beta&tag=one&tag=two|"
        f"{expected_body_hash}"
    )

    assert body_sha256(raw_body) == expected_body_hash
    assert (
        canonical_string(
            timestamp=1_760_000_000,
            nonce="fixed-nonce-1234",
            method="get",
            path_with_query="/v1/products?category=alpha%20beta&tag=one&tag=two",
            raw_body=raw_body,
        )
        == expected_canonical
    )
    assert (
        sign_request(
            api_secret="unit-test-secret",
            timestamp=1_760_000_000,
            nonce="fixed-nonce-1234",
            method="get",
            path_with_query="/v1/products?category=alpha%20beta&tag=one&tag=two",
            raw_body=raw_body,
        )
        == "fe509c3bdac5f313fd430537ad558a6b02f574837f858476a0aa5e021a1e393f"
    )


def test_get_hashes_empty_bytes_and_emits_lowercase_hex() -> None:
    signature = sign_request(
        api_secret=b"another-test-key",
        timestamp=1_760_000_001,
        nonce="nonce-for-empty-body",
        method="GET",
        path_with_query="/v1/products",
        raw_body=b"",
    )

    assert body_sha256(b"") == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    assert re.fullmatch(r"[0-9a-f]{64}", signature)


def test_raw_request_bytes_are_not_decoded_or_json_reserialized() -> None:
    compact = b'{"a":1}'
    spaced = b'{ "a" : 1 }'
    non_utf8 = b"\xff\x00\x80"

    compact_signature = sign_request(
        api_secret="test-key",
        timestamp=1,
        nonce="nonce-exact-0001",
        method="GET",
        path_with_query="/v1/account",
        raw_body=compact,
    )
    spaced_signature = sign_request(
        api_secret="test-key",
        timestamp=1,
        nonce="nonce-exact-0001",
        method="GET",
        path_with_query="/v1/account",
        raw_body=spaced,
    )

    assert compact_signature != spaced_signature
    assert (
        body_sha256(non_utf8) == "ef192b7af54e943f206ab27075ec1805384c972c9959fc5820f1fa7d5268fcef"
    )
    with pytest.raises(VietShareConfigurationError, match="exact bytes"):
        body_sha256('{"a":1}')  # type: ignore[arg-type]


def test_target_and_url_share_the_same_ordered_query_encoding() -> None:
    target = build_request_target(
        base_url=PRODUCTION_BASE_URL,
        endpoint="/products",
        query=(("z", "last value"), ("a", "first/value"), ("z", "again")),
    )

    expected_path = "/v1/products?z=last+value&a=first%2Fvalue&z=again"
    assert target.path_with_query == expected_path
    assert target.url == f"https://token.vietshare.site{expected_path}"
    assert "last+value" not in repr(target)
    assert "<redacted>" in repr(target)


@pytest.mark.parametrize(
    ("endpoint", "expected_path"),
    [
        ("/account", "/v1/account"),
        ("/products", "/v1/products"),
        ("/catalog", "/v1/catalog"),
        ("/products/42", "/v1/products/42"),
        ("/stock/42", "/v1/stock/42"),
        ("/v1/products", "/v1/products"),
    ],
)
def test_all_and_only_documented_read_targets_retain_v1(endpoint: str, expected_path: str) -> None:
    target = build_request_target(base_url=PRODUCTION_BASE_URL, endpoint=endpoint)

    assert target.path_with_query == expected_path
    assert target.url == f"https://token.vietshare.site{expected_path}"


@pytest.mark.parametrize("endpoint", ["/orders", "/orders/history", "/top-up", "/refund"])
def test_request_builder_rejects_every_non_read_route(endpoint: str) -> None:
    with pytest.raises(VietShareConfigurationError, match="allowed VietShare read route"):
        build_request_target(base_url=PRODUCTION_BASE_URL, endpoint=endpoint)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/products"),
        ("GET", "/v1/orders"),
        ("GET", "/v1/orders/history"),
    ],
)
def test_low_level_signer_cannot_sign_writes_or_order_routes(method: str, path: str) -> None:
    with pytest.raises(VietShareConfigurationError):
        sign_request(
            api_secret="synthetic-test-secret",
            timestamp=1,
            nonce="read-only-nonce-01",
            method=method,
            path_with_query=path,
            raw_body=b"",
        )


def test_signed_request_preserves_exact_body_and_auth_headers() -> None:
    credentials = VietShareCredentials(
        api_id="synthetic-shop-id",
        api_secret="synthetic-api-secret",
    )
    raw_body = b"not-json\x00and-still-exact"

    request = build_signed_read_request(
        credentials=credentials,
        base_url=PRODUCTION_BASE_URL,
        endpoint="/products",
        timestamp=1_760_000_005,
        nonce="nonce-request-0005",
        query=(("continuation", "future-token"), ("filter", "second")),
        raw_body=raw_body,
    )

    assert request.method == "GET"
    assert request.url.endswith("/v1/products?continuation=future-token&filter=second")
    assert request.path_with_query == ("/v1/products?continuation=future-token&filter=second")
    assert request.body is raw_body
    assert dict(request.headers) == {
        "X-Shop-API-ID": "synthetic-shop-id",
        "X-Timestamp": "1760000005",
        "X-Nonce": "nonce-request-0005",
        "X-Signature": request.headers["X-Signature"],
    }
    assert re.fullmatch(r"[0-9a-f]{64}", request.headers["X-Signature"])


def test_signing_and_request_representations_redact_auth_and_payloads() -> None:
    credentials = VietShareCredentials(
        api_id="id-must-not-print",
        api_secret="secret-must-not-print",
    )
    request = build_signed_read_request(
        credentials=credentials,
        base_url=PRODUCTION_BASE_URL,
        endpoint="/account",
        timestamp=1,
        nonce="nonce-redact-0001",
        raw_body=b"payload-must-not-print",
    )

    combined = " ".join((repr(credentials), repr(request), repr(request.headers)))
    assert "id-must-not-print" not in combined
    assert "secret-must-not-print" not in combined
    assert request.headers["X-Signature"] not in combined
    assert "payload-must-not-print" not in combined
    assert "<redacted>" in combined


def test_configuration_errors_never_echo_rejected_values() -> None:
    sensitive_invalid_path = "/private/response-content"

    with pytest.raises(VietShareConfigurationError) as caught:
        canonical_string(
            timestamp=1,
            nonce="nonce-safe-0001",
            method="GET",
            path_with_query=sensitive_invalid_path,
            raw_body=b"",
        )

    assert sensitive_invalid_path not in str(caught.value)
