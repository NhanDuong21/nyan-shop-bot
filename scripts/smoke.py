"""Read-only smoke test for the local Docker stack."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("NYAN_API_URL", "http://127.0.0.1:8000")
ADMIN_URL = os.environ.get("NYAN_ADMIN_URL", "http://127.0.0.1:5173")


def get(url: str) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - fixed localhost
        return response.status, response.read(), response.headers.get("Content-Type", "")


def wait_for(url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if get(url)[0] == 200:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {url}")


def assert_missing_write_route(path: str) -> None:
    request = urllib.request.Request(f"{API_URL}{path}", data=b"{}", method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(request, timeout=5)  # noqa: S310 - fixed localhost
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise AssertionError(f"{path} returned unexpected HTTP {error.code}") from error
    else:
        raise AssertionError(f"Forbidden write route exists: {path}")


def main() -> int:
    wait_for(f"{API_URL}/readyz")
    wait_for(ADMIN_URL)

    _, health_bytes, _ = get(f"{API_URL}/healthz")
    health = json.loads(health_bytes)
    assert health == {
        "status": "ok",
        "supplier_mode": "mock",
        "payment_mode": "disabled",
        "allow_real_purchases": False,
        "read_only": True,
    }

    _, catalog_bytes, _ = get(f"{API_URL}/api/v1/catalog")
    catalog = json.loads(catalog_bytes)
    assert catalog["mode"] == "mock"
    assert len(catalog["items"]) == 3

    _, admin_html, content_type = get(ADMIN_URL)
    assert "text/html" in content_type
    assert b"Nyan Shop Bot" in admin_html

    for path in ("/orders", "/topup", "/refund", "/delivery"):
        assert_missing_write_route(path)

    print("Mock API/admin smoke test passed; no live operation was called.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
