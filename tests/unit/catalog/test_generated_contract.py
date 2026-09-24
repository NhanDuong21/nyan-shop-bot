"""Drift tests for FastAPI OpenAPI and generated UI fixture inputs."""

import json
from pathlib import Path
from typing import Any

from nyan_shop_bot.catalog.generate import rendered_artifacts, write_generated_artifacts
from nyan_shop_bot.catalog.models import CatalogResponse

ROOT = Path(__file__).resolve().parents[3]
GENERATED = ROOT / "generated"


def decode_json(content: bytes) -> dict[str, Any]:
    value = json.loads(content)
    assert isinstance(value, dict)
    return value


def test_tracked_artifacts_exactly_match_code_generation() -> None:
    for filename, expected in rendered_artifacts().items():
        assert (GENERATED / filename).read_bytes() == expected


def test_generator_can_target_an_isolated_directory(tmp_path: Path) -> None:
    write_generated_artifacts(tmp_path)

    assert {
        path.name: path.read_bytes() for path in sorted(tmp_path.iterdir())
    } == rendered_artifacts()


def test_openapi_is_client_input_for_read_only_catalog_routes() -> None:
    document = decode_json(rendered_artifacts()["openapi.json"])
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    assert set(paths["/api/v1/catalog"]) == {"get"}
    assert set(paths["/api/v1/catalog/sources"]) == {"get"}
    assert set(paths["/api/v1/catalog/{product_id}"]) == {"get"}
    assert set(paths["/api/v1/capabilities"]) == {"get"}
    assert set(paths["/api/v1/storefront/catalog"]) == {"get"}
    assert set(paths["/api/v1/storefront/catalog/{product_id}"]) == {"get"}
    admin_path = "/api/v1/admin/catalog-curation"
    assert set(paths[admin_path]) == {"get", "put"}
    assert all(
        method not in path
        for name, path in paths.items()
        if name != admin_path
        for method in ("post", "put", "patch", "delete")
    )
    assert not any(
        forbidden in path
        for path in paths
        for forbidden in ("orders", "purchase", "payment", "topup", "refund", "delivery")
    )

    money = schemas["Money"]
    assert set(money["required"]) == {"amount_minor", "currency", "unit"}
    assert money["properties"]["amount_minor"]["type"] == "integer"
    assert money["properties"]["currency"]["pattern"] == "^[A-Z]{3}$"
    assert money["properties"]["unit"]["const"] == "minor"

    mapping = schemas["SupplierMapping"]
    assert set(mapping["required"]) == {
        "supplier_product",
        "supplier_variant",
        "approval",
    }
    assert schemas["MappingApproval"]["discriminator"]["propertyName"] == "status"

    catalog_union = schemas["CatalogListResponse"]["anyOf"]
    assert {branch["$ref"] for branch in catalog_union} == {
        "#/components/schemas/CatalogResponse",
        "#/components/schemas/AggregateCatalogResponse",
    }
    aggregate = schemas["AggregateCatalogResponse"]
    assert aggregate["properties"]["mode"]["const"] == "multi-readonly"
    source_parameter = paths["/api/v1/catalog"]["get"]["parameters"][0]
    assert "all" in source_parameter["schema"]["anyOf"][0]["enum"]

    workspace = schemas["CatalogCurationWorkspace"]
    assert workspace["properties"]["read_only"]["const"] is True
    assert workspace["properties"]["supplier_writes_enabled"]["const"] is False
    save_request = schemas["CatalogCurationSaveRequest"]
    assert set(save_request["required"]) == {"expected_revision", "listings"}

    storefront_product = schemas["StorefrontProduct"]
    assert set(storefront_product["properties"]) == {
        "id",
        "name",
        "description",
        "category",
        "price",
        "availability",
        "read_only",
    }
    storefront = schemas["StorefrontCatalogResponse"]
    assert storefront["properties"]["supplier_provenance_exposed"]["const"] is False
    assert storefront["properties"]["purchase_enabled"]["const"] is False
    assert storefront["properties"]["payment_enabled"]["const"] is False
    detail_schema = paths["/api/v1/storefront/catalog/{product_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert detail_schema["discriminator"]["propertyName"] == "state"


def test_ui_fixtures_cover_and_validate_every_required_state() -> None:
    fixtures = decode_json(rendered_artifacts()["catalog-ui-fixtures.json"])
    scenarios = fixtures["scenarios"]

    assert set(scenarios) == {"fresh", "stale", "empty", "error"}
    for name, value in scenarios.items():
        response = CatalogResponse.model_validate(value)
        assert response.state.value == name


def test_fresh_fixture_retains_the_merged_admin_projection() -> None:
    fixtures = decode_json(rendered_artifacts()["catalog-ui-fixtures.json"])

    for item in fixtures["scenarios"]["fresh"]["items"]:
        assert item["supplier"] == "mock"
        assert item["mode"] == "mock"
        assert item["price"] == item["variants"][0]["price"]
        assert item["available_quantity"] == item["variants"][0]["available_quantity"]
