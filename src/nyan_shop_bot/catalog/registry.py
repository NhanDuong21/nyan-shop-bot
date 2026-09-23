"""Explicit source routing for one or more read-only catalog readers."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from nyan_shop_bot.catalog.models import (
    CatalogMode,
    CatalogSourceOption,
    CatalogSourcesResponse,
    CatalogSupplier,
)
from nyan_shop_bot.catalog.ports import CatalogReader


class CatalogSourceSelectionRequired(LookupError):
    """Raised when a multi-source caller omitted the source identity."""


class CatalogSourceUnavailable(LookupError):
    """Raised when a caller requested a source not configured in this runtime."""


_MODE_BY_SUPPLIER: dict[CatalogSupplier, CatalogMode] = {
    "mock": "mock",
    "khommo": "khommo-readonly",
    "vietshare": "vietshare-readonly",
}


class CatalogRegistry:
    """Immutable mapping that never guesses between multiple supplier readers."""

    def __init__(
        self,
        readers: Mapping[CatalogSupplier, CatalogReader],
        *,
        default_source: CatalogSupplier | None = None,
    ) -> None:
        if not readers:
            raise ValueError("catalog registry requires at least one reader")
        copied = dict(readers)
        if default_source is not None and default_source not in copied:
            raise ValueError("default catalog source must be configured")
        if len(copied) == 1 and default_source is None:
            default_source = next(iter(copied))
        if len(copied) > 1 and default_source is not None:
            raise ValueError("multi-source catalog registry cannot guess a default source")
        self._readers = MappingProxyType(copied)
        self._default_source = default_source

    @property
    def sources(self) -> tuple[CatalogSupplier, ...]:
        """Return configured sources in stable display order."""
        return tuple(self._readers)

    @property
    def selection_required(self) -> bool:
        return len(self._readers) > 1

    @property
    def source_response(self) -> CatalogSourcesResponse:
        return CatalogSourcesResponse(
            sources=tuple(
                CatalogSourceOption(
                    supplier=supplier,
                    mode=_MODE_BY_SUPPLIER[supplier],
                )
                for supplier in self.sources
            ),
            selection_required=self.selection_required,
        )

    def resolve(self, source: CatalogSupplier | None = None) -> CatalogReader:
        """Resolve explicitly in multi mode and fail closed for absent sources."""
        selected = source if source is not None else self._default_source
        if selected is None:
            raise CatalogSourceSelectionRequired("catalog source selection is required")
        try:
            return self._readers[selected]
        except KeyError as exc:
            raise CatalogSourceUnavailable("catalog source is not configured") from exc
