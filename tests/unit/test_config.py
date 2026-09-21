"""Tests for Phase 0 kill switches."""

import pytest
from pydantic import ValidationError

from nyan_shop_bot.config import Settings


def test_safe_defaults_are_mock_only(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SUPPLIER_MODE",
        "PAYMENT_MODE",
        "ALLOW_REAL_PURCHASES",
        "KHOMMO_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.supplier_mode == "mock"
    assert settings.payment_mode == "disabled"
    assert settings.allow_real_purchases is False


@pytest.mark.parametrize(
    ("environment", "value"),
    [
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

    with pytest.raises(ValidationError, match="Read-only runtime requires"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_generic_live_supplier_mode_remains_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPLIER_MODE", "live")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_khommo_readonly_requires_local_secret_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPPLIER_MODE", "khommo-readonly")
    monkeypatch.delenv("KHOMMO_API_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="requires local KHOMMO_API_TOKEN"):
        Settings(_env_file=None)  # type: ignore[call-arg]

    secret = "local-secret-marker"
    monkeypatch.setenv("KHOMMO_API_TOKEN", secret)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.supplier_mode == "khommo-readonly"
    assert settings.payment_mode == "disabled"
    assert settings.allow_real_purchases is False
    assert secret not in repr(settings)


def test_khommo_readonly_cannot_start_outside_local_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SUPPLIER_MODE", "khommo-readonly")
    monkeypatch.setenv("KHOMMO_API_TOKEN", "synthetic-secret")

    with pytest.raises(ValidationError, match="allowed only with APP_ENV=local"):
        Settings(_env_file=None)  # type: ignore[call-arg]
