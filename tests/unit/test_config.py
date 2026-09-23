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
        "VIETSHARE_API_ID",
        "VIETSHARE_API_SECRET",
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


def test_vietshare_readonly_requires_both_local_credentials_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPPLIER_MODE", "vietshare-readonly")
    monkeypatch.delenv("VIETSHARE_API_ID", raising=False)
    monkeypatch.delenv("VIETSHARE_API_SECRET", raising=False)

    with pytest.raises(ValidationError, match="requires local VIETSHARE_API_ID"):
        Settings(_env_file=None)  # type: ignore[call-arg]

    api_id = "synthetic-api-id-private"
    api_secret = "synthetic-api-secret-private"
    monkeypatch.setenv("VIETSHARE_API_ID", api_id)
    with pytest.raises(ValidationError, match="requires local VIETSHARE_API_SECRET"):
        Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("VIETSHARE_API_SECRET", api_secret)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.supplier_mode == "vietshare-readonly"
    assert settings.payment_mode == "disabled"
    assert settings.allow_real_purchases is False
    assert api_id not in repr(settings)
    assert api_secret not in repr(settings)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "api.local"])
def test_vietshare_readonly_rejects_non_loopback_or_nonlocal_runtime(host: str) -> None:
    with pytest.raises(ValidationError, match="APP_HOST to be loopback"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            app_env="local",
            app_host=host,
            supplier_mode="vietshare-readonly",
            vietshare_api_id="synthetic-id",
            vietshare_api_secret="synthetic-secret",
        )

    with pytest.raises(ValidationError, match="allowed only with APP_ENV=local"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            app_env="test",
            app_host="127.0.0.1",
            supplier_mode="vietshare-readonly",
            vietshare_api_id="synthetic-id",
            vietshare_api_secret="synthetic-secret",
        )


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "api.local"])
def test_khommo_readonly_rejects_every_non_loopback_bind(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_HOST", host)
    monkeypatch.setenv("SUPPLIER_MODE", "khommo-readonly")
    monkeypatch.setenv("KHOMMO_API_TOKEN", "synthetic-secret")

    with pytest.raises(ValidationError, match="APP_HOST to be loopback"):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "localhost"])
def test_khommo_readonly_accepts_only_explicit_loopback_hosts(host: str) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="local",
        app_host=host,
        supplier_mode="khommo-readonly",
        khommo_api_token="synthetic-secret",
    )

    assert settings.app_host == host


@pytest.mark.parametrize(
    "invalid_settings",
    [
        {"app_env": "test", "supplier_mode": "khommo-readonly"},
        {"app_host": "0.0.0.0", "supplier_mode": "khommo-readonly"},
        {"payment_mode": "live", "supplier_mode": "khommo-readonly"},
        {"allow_real_purchases": True, "supplier_mode": "khommo-readonly"},
        {"supplier_mode": "live"},
    ],
)
def test_rejected_configuration_hides_every_secret_input(
    invalid_settings: dict[str, object],
) -> None:
    supplier_secret = "SYNTHETIC_KHOMMO_SECRET_MUST_NOT_RENDER"
    vietshare_id = "SYNTHETIC_VIETSHARE_ID_MUST_NOT_RENDER"
    vietshare_secret = "SYNTHETIC_VIETSHARE_SECRET_MUST_NOT_RENDER"
    telegram_secret = "SYNTHETIC_TELEGRAM_SECRET_MUST_NOT_RENDER"
    values: dict[str, object] = {
        "khommo_api_token": supplier_secret,
        "vietshare_api_id": vietshare_id,
        "vietshare_api_secret": vietshare_secret,
        "telegram_bot_token": telegram_secret,
        **invalid_settings,
    }

    with pytest.raises(ValidationError) as captured:
        Settings(_env_file=None, **values)  # type: ignore[call-arg]

    rendered = f"{captured.value!s}\n{captured.value!r}"
    assert supplier_secret not in rendered
    assert vietshare_id not in rendered
    assert vietshare_secret not in rendered
    assert telegram_secret not in rendered
