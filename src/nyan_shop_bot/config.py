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
    """Runtime settings with mock defaults and one explicit local live-read mode."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["local", "test"] = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = (
        "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot"
    )
    supplier_mode: Literal["mock", "khommo-readonly"] = "mock"
    payment_mode: Literal["disabled", "mock", "live"] = "disabled"
    allow_real_purchases: bool = False
    khommo_api_token: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None

    @model_validator(mode="after")
    def enforce_read_only_safety(self) -> Self:
        """Keep payment and purchase guards independent from supplier read access."""
        if self.payment_mode != "disabled" or self.allow_real_purchases:
            raise UnsafeRuntimeConfiguration(
                "Read-only runtime requires PAYMENT_MODE=disabled and ALLOW_REAL_PURCHASES=false"
            )

        if self.supplier_mode == "khommo-readonly":
            if self.app_env != "local":
                raise UnsafeRuntimeConfiguration(
                    "SUPPLIER_MODE=khommo-readonly is allowed only with APP_ENV=local"
                )
            if not is_loopback_host(self.app_host):
                raise UnsafeRuntimeConfiguration(
                    "SUPPLIER_MODE=khommo-readonly requires APP_HOST to be loopback"
                )
            token = self.khommo_api_token
            if token is None or not token.get_secret_value():
                raise UnsafeRuntimeConfiguration(
                    "SUPPLIER_MODE=khommo-readonly requires local KHOMMO_API_TOKEN"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
