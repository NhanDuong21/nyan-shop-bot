"""Catalog source selection stays explicit and fail-closed."""

import pytest

from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.catalog.registry import (
    CatalogRegistry,
    CatalogSourceSelectionRequired,
    CatalogSourceUnavailable,
)


def test_single_source_registry_preserves_backward_compatible_default() -> None:
    reader = FakeCatalogReader()
    registry = CatalogRegistry({"mock": reader})

    assert registry.sources == ("mock",)
    assert registry.selection_required is False
    assert registry.resolve() is reader
    assert registry.source_response.model_dump(mode="json") == {
        "sources": [{"supplier": "mock", "mode": "mock", "read_only": True}],
        "selection_required": False,
    }


def test_multi_source_registry_requires_an_available_explicit_source() -> None:
    khommo = FakeCatalogReader()
    vietshare = FakeCatalogReader()
    registry = CatalogRegistry({"khommo": khommo, "vietshare": vietshare})

    assert registry.sources == ("khommo", "vietshare")
    assert registry.selection_required is True
    assert registry.resolve("khommo") is khommo
    assert registry.resolve("vietshare") is vietshare
    with pytest.raises(CatalogSourceSelectionRequired):
        registry.resolve()
    with pytest.raises(CatalogSourceUnavailable):
        registry.resolve("mock")


def test_multi_source_registry_rejects_a_hidden_default() -> None:
    with pytest.raises(ValueError, match="cannot guess a default"):
        CatalogRegistry(
            {"khommo": FakeCatalogReader(), "vietshare": FakeCatalogReader()},
            default_source="khommo",
        )
