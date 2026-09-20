"""Deterministic VietShare v1 request targeting and HMAC signing."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from nyan_shop_bot.suppliers.vietshare.models import (
    VietShareConfigurationError,
    VietShareCredentials,
    VietShareRequest,
)

PRODUCTION_BASE_URL = "https://token.vietshare.site/v1"

_ALLOWED_READ_PATH = re.compile(r"^/v1/(?:account|products|catalog|products/[0-9]+|stock/[0-9]+)$")


@dataclass(frozen=True, repr=False)
class RequestTarget:
    """One URL and canonical path produced from the same ordered query sequence."""

    url: str
    path_with_query: str

    def __repr__(self) -> str:
        return "RequestTarget(url=<redacted>, path_with_query=<redacted>)"


def _raw_bytes(raw_body: bytes) -> bytes:
    if type(raw_body) is not bytes:
        raise VietShareConfigurationError("Raw request body must be exact bytes")
    return raw_body


def body_sha256(raw_body: bytes) -> str:
    """Hash the caller's bytes exactly, without decoding or reserialization."""
    return hashlib.sha256(_raw_bytes(raw_body)).hexdigest()


def _timestamp_text(timestamp: int) -> str:
    if type(timestamp) is not int or timestamp < 0:
        raise VietShareConfigurationError("Timestamp must be a non-negative integer Unix second")
    return str(timestamp)


def _nonce_text(nonce: str) -> str:
    if type(nonce) is not str or not 12 <= len(nonce) <= 128:
        raise VietShareConfigurationError("Nonce must contain 12 to 128 characters")
    if "\r" in nonce or "\n" in nonce:
        raise VietShareConfigurationError("Nonce must not contain line breaks")
    return nonce


def _method_text(method: str) -> str:
    if type(method) is not str or not method or not method.isascii() or not method.isalpha():
        raise VietShareConfigurationError("HTTP method must contain ASCII letters")
    canonical = method.upper()
    if canonical != "GET":
        raise VietShareConfigurationError("Only GET requests can be signed by this read adapter")
    return canonical


def _canonical_path(path_with_query: str) -> str:
    if type(path_with_query) is not str:
        raise VietShareConfigurationError("Canonical path must be text")
    path = path_with_query.partition("?")[0]
    if not (path == "/v1" or path.startswith("/v1/")):
        raise VietShareConfigurationError("Canonical path must include the /v1 prefix")
    if "#" in path_with_query or "\r" in path_with_query or "\n" in path_with_query:
        raise VietShareConfigurationError("Canonical path contains an invalid character")
    if _ALLOWED_READ_PATH.fullmatch(path) is None:
        raise VietShareConfigurationError("Canonical path is not an allowed VietShare read route")
    return path_with_query


def canonical_string(
    *,
    timestamp: int,
    nonce: str,
    method: str,
    path_with_query: str,
    raw_body: bytes,
) -> str:
    """Build the supplier's exact pipe-delimited signing payload."""
    return "|".join(
        (
            _timestamp_text(timestamp),
            _nonce_text(nonce),
            _method_text(method),
            _canonical_path(path_with_query),
            body_sha256(raw_body),
        )
    )


def sign_request(
    *,
    api_secret: str | bytes,
    timestamp: int,
    nonce: str,
    method: str,
    path_with_query: str,
    raw_body: bytes,
) -> str:
    """Return lowercase hexadecimal HMAC-SHA256 for exact request bytes."""
    if type(api_secret) is str:
        if not api_secret:
            raise VietShareConfigurationError("API secret must not be empty")
        secret_bytes = api_secret.encode("utf-8")
    elif type(api_secret) is bytes:
        if not api_secret:
            raise VietShareConfigurationError("API secret must not be empty")
        secret_bytes = api_secret
    else:
        raise VietShareConfigurationError("API secret must be text or bytes")

    payload = canonical_string(
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path_with_query=path_with_query,
        raw_body=raw_body,
    ).encode("utf-8")
    return hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest()


def _base_parts(base_url: str) -> tuple[str, str, str]:
    if type(base_url) is not str:
        raise VietShareConfigurationError("Base URL must be text")
    split = urlsplit(base_url)
    if (
        split.scheme != "https"
        or not split.netloc
        or split.username is not None
        or split.password is not None
        or split.query
        or split.fragment
        or split.path.rstrip("/") != "/v1"
    ):
        raise VietShareConfigurationError("Base URL must be an HTTPS origin ending in /v1")
    return split.scheme, split.netloc, "/v1"


def _endpoint_path(endpoint: str) -> str:
    if type(endpoint) is not str:
        raise VietShareConfigurationError("Read endpoint must be text")
    if endpoint.startswith("/v1/"):
        path = endpoint
    else:
        path = f"/v1/{endpoint.lstrip('/')}"
    if _ALLOWED_READ_PATH.fullmatch(path) is None:
        raise VietShareConfigurationError("Endpoint is not an allowed VietShare read route")
    return path


def _ordered_query(query: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if isinstance(query, (str, bytes, bytearray)) or not isinstance(query, Sequence):
        raise VietShareConfigurationError("Query must be an ordered sequence of text pairs")
    copied: list[tuple[str, str]] = []
    for item in query:
        if type(item) is not tuple or len(item) != 2:
            raise VietShareConfigurationError("Query must be an ordered sequence of text pairs")
        name, value = item
        if type(name) is not str or type(value) is not str:
            raise VietShareConfigurationError("Query names and values must be text")
        copied.append((name, value))
    return tuple(copied)


def build_request_target(
    *,
    base_url: str,
    endpoint: str,
    query: Sequence[tuple[str, str]] = (),
) -> RequestTarget:
    """Build URL and canonical path once, preserving caller-supplied query order."""
    scheme, netloc, base_path = _base_parts(base_url)
    path = _endpoint_path(endpoint)
    if not path.startswith(f"{base_path}/"):
        raise VietShareConfigurationError("Read endpoint must remain below /v1")
    encoded_query = urlencode(_ordered_query(query), doseq=False)
    path_with_query = f"{path}?{encoded_query}" if encoded_query else path
    url = urlunsplit((scheme, netloc, path, encoded_query, ""))
    return RequestTarget(url=url, path_with_query=path_with_query)


def build_signed_read_request(
    *,
    credentials: VietShareCredentials,
    base_url: str,
    endpoint: str,
    timestamp: int,
    nonce: str,
    query: Sequence[tuple[str, str]] = (),
    raw_body: bytes = b"",
) -> VietShareRequest:
    """Create one signed GET request for an allow-listed v1 read endpoint."""
    body = _raw_bytes(raw_body)
    target = build_request_target(base_url=base_url, endpoint=endpoint, query=query)
    signature = sign_request(
        api_secret=credentials.secret_bytes,
        timestamp=timestamp,
        nonce=nonce,
        method="GET",
        path_with_query=target.path_with_query,
        raw_body=body,
    )
    return VietShareRequest(
        method="GET",
        url=target.url,
        path_with_query=target.path_with_query,
        headers={
            "X-Shop-API-ID": credentials.api_id,
            "X-Timestamp": _timestamp_text(timestamp),
            "X-Nonce": _nonce_text(nonce),
            "X-Signature": signature,
        },
        body=body,
    )
