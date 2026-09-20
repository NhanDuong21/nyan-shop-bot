"""Generate deterministic client-contract artifacts from the FastAPI application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nyan_shop_bot.catalog.mock import fake_catalog_scenarios
from nyan_shop_bot.config import Settings
from nyan_shop_bot.main import create_app

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIRECTORY = ROOT / "generated"


class _ContractDatabase:
    """Database-free probe used only while constructing the OpenAPI document."""

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _contract_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        app_host="127.0.0.1",
        app_port=8000,
        database_url="postgresql+asyncpg://127.0.0.1:5432/contract",
        supplier_mode="mock",
        payment_mode="disabled",
        allow_real_purchases=False,
        telegram_bot_token=None,
    )


def openapi_client_input() -> dict[str, Any]:
    """Return the canonical OpenAPI input consumed by generated UI clients."""
    application = create_app(settings=_contract_settings(), database=_ContractDatabase())
    return application.openapi()


def ui_fixture_input() -> dict[str, Any]:
    """Return all validated catalog states as one stable UI fixture document."""
    return {
        "schema_version": 1,
        "source": "FastAPI CatalogResponse",
        "scenarios": {
            scenario.value: response.model_dump(mode="json")
            for scenario, response in fake_catalog_scenarios().items()
        },
    }


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def rendered_artifacts() -> dict[str, bytes]:
    """Render every tracked artifact without writing the working tree."""
    return {
        "openapi.json": _json_bytes(openapi_client_input()),
        "catalog-ui-fixtures.json": _json_bytes(ui_fixture_input()),
    }


def write_generated_artifacts(output_directory: Path = DEFAULT_OUTPUT_DIRECTORY) -> None:
    """Write the canonical artifacts to an explicit directory."""
    output_directory.mkdir(parents=True, exist_ok=True)
    for filename, content in rendered_artifacts().items():
        (output_directory / filename).write_bytes(content)


if __name__ == "__main__":
    write_generated_artifacts()
