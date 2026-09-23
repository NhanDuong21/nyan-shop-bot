"""Typed, fail-closed application configuration."""

from functools import lru_cache
from ipaddress import ip_address
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UnsafeRuntimeConfiguration(ValueError):
    """Raised when runtime settings could escape the approved read-only boundary."""


def is_loopback_host(value: str) -> bool:
    """Accept only an explicit localhost name or loopback IP address."""
    if value.lower() == "localhost":
        return True
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    """Runtime settings with mock defaults and explicit local live-read modes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    app_env: Literal["local", "test"] = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = (
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot"
    )
    supplier_mode: Literal[
        "mock",
        "khommo-readonly",
        "vietshare-readonly",
        "multi-readonly",
    ] = "mock"
    payment_mode: Literal["disabled", "mock", "live"] = "disabled"
    allow_real_purchases: bool = False
    khommo_api_token: SecretStr | None = None
    vietshare_api_id: SecretStr | None = None
    vietshare_api_secret: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None

    @model_validator(mode="after")
    def enforce_read_only_safety(self) -> Self:
        """Keep payment and purchase guards independent from supplier read access."""
        if self.payment_mode != "disabled" or self.allow_real_purchases:
            raise UnsafeRuntimeConfiguration(
                "Read-only runtime requires PAYMENT_MODE=disabled and ALLOW_REAL_PURCHASES=false"
            )

        if self.supplier_mode != "mock":
            if self.app_env != "local":
                raise UnsafeRuntimeConfiguration(
                    f"SUPPLIER_MODE={self.supplier_mode} is allowed only with APP_ENV=local"
                )
            if not is_loopback_host(self.app_host):
                raise UnsafeRuntimeConfiguration(
                    f"SUPPLIER_MODE={self.supplier_mode} requires APP_HOST to be loopback"
                )

        if self.supplier_mode in {"khommo-readonly", "multi-readonly"}:
            token = self.khommo_api_token
            if token is None or not token.get_secret_value():
                raise UnsafeRuntimeConfiguration(
                    f"SUPPLIER_MODE={self.supplier_mode} requires local KHOMMO_API_TOKEN"
                )
        if self.supplier_mode in {"vietshare-readonly", "multi-readonly"}:
            api_id = self.vietshare_api_id
            api_secret = self.vietshare_api_secret
            if api_id is None or not api_id.get_secret_value():
                raise UnsafeRuntimeConfiguration(
                    f"SUPPLIER_MODE={self.supplier_mode} requires local VIETSHARE_API_ID"
                )
            if api_secret is None or not api_secret.get_secret_value():
                raise UnsafeRuntimeConfiguration(
                    f"SUPPLIER_MODE={self.supplier_mode} requires local VIETSHARE_API_SECRET"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
