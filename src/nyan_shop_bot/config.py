"""Typed, fail-closed application configuration."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UnsafePhaseZeroConfiguration(ValueError):
    """Raised when Phase 0 is configured to perform live operations."""


class Settings(BaseSettings):
    """Runtime settings with intentionally safe Phase 0 defaults."""

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
    supplier_mode: Literal["mock", "live"] = "mock"
    payment_mode: Literal["disabled", "mock", "live"] = "disabled"
    allow_real_purchases: bool = False
    telegram_bot_token: SecretStr | None = None

    @model_validator(mode="after")
    def enforce_phase_zero_safety(self) -> Self:
        """Reject every live-money or live-supplier combination in this foundation."""
        unsafe = (
            self.supplier_mode != "mock"
            or self.payment_mode != "disabled"
            or self.allow_real_purchases
        )
        if unsafe:
            raise UnsafePhaseZeroConfiguration(
                "Phase 0 only supports SUPPLIER_MODE=mock, PAYMENT_MODE=disabled, "
                "and ALLOW_REAL_PURCHASES=false"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
