"""Customer-copy safeguards shared by API and Telegram projections."""

from __future__ import annotations

import re

_UPSTREAM_BRAND_PATTERN = re.compile(
    r"(?:kho[\s._-]*mmo|viet[\s._-]*share)",
    flags=re.IGNORECASE,
)


def customer_text(value: str) -> str:
    """White-label known upstream brands in owner-authored storefront copy."""
    return _UPSTREAM_BRAND_PATTERN.sub("Nyan", value)
