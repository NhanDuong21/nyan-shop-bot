"""Tests for Phase 0 kill switches."""

import pytest
from pydantic import ValidationError

from nyan_shop_bot.config import Settings


def test_safe_defaults_are_mock_only(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SUPPLIER_MODE", "PAYMENT_MODE", "ALLOW_REAL_PURCHASES"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.supplier_mode == "mock"
    assert settings.payment_mode == "disabled"
    assert settings.allow_real_purchases is False


@pytest.mark.parametrize(
    ("environment", "value"),
    [
        ("SUPPLIER_MODE", "live"),
        ("PAYMENT_MODE", "mock"),
        ("PAYMENT_MODE", "live"),
        ("ALLOW_REAL_PURCHASES", "true"),
    ],
)
def test_unsafe_modes_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    value: str,
) -> None:
    monkeypatch.setenv(environment, value)

    with pytest.raises(ValidationError, match="Phase 0 only supports"):
        Settings(_env_file=None)  # type: ignore[call-arg]
