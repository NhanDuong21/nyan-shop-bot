"""Explicit source routing for one or more read-only catalog readers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import MappingProxyType

from nyan_shop_bot.catalog.models import (
    AggregateCatalogResponse,
    AggregateCatalogState,
    AggregateSourceReport,
    Capability,
    CapabilityStatus,
    CatalogError,
    CatalogErrorCode,
    CatalogMode,
    CatalogResponse,
    CatalogSourceOption,
    CatalogSourcesResponse,
    CatalogState,
    CatalogSupplier,
    LiveCatalogSupplier,
    SupplierCapabilities,
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
            aggregate_available=self.aggregate_available,
        )

    @property
    def aggregate_available(self) -> bool:
        """Return whether both verified live readers can form a combined view."""
        return set(self.sources) == {"khommo", "vietshare"}

    @property
    def aggregate_capabilities(self) -> SupplierCapabilities:
        """Expose the strict intersection of read capabilities for the combined view."""
        if not self.aggregate_available:
            raise CatalogSourceUnavailable("aggregate catalog is not configured")
        readers = tuple(self._readers[source] for source in self.sources)

        def read_capability(name: str) -> Capability:
            values = tuple(getattr(reader.capabilities, name) for reader in readers)
            if all(value.status is CapabilityStatus.ENABLED for value in values):
                return Capability(status=CapabilityStatus.ENABLED, reason=None)
            return Capability(
                status=CapabilityStatus.UNSUPPORTED,
                reason="At least one aggregate source does not support this read operation.",
            )

        locked = Capability(
            status=CapabilityStatus.DISABLED,
            reason=(
                "Aggregate catalog is read-only; live money and delivery operations are disabled."
            ),
        )
        return SupplierCapabilities(
            catalog_read=read_capability("catalog_read"),
            catalog_detail=read_capability("catalog_detail"),
            purchase=locked,
            payment=locked,
            top_up=locked,
            refund=locked,
            delivery=locked,
        )

    @staticmethod
    def _unavailable_report(source: LiveCatalogSupplier) -> AggregateSourceReport:
        return AggregateSourceReport(
            supplier=source,
            mode=_MODE_BY_SUPPLIER[source],
            state=CatalogState.ERROR,
            freshness=None,
            error=CatalogError(
                code=CatalogErrorCode.SOURCE_UNAVAILABLE,
                message="This read-only catalog source is unavailable.",
                retryable=True,
            ),
            item_count=0,
        )

    @staticmethod
    def _report_from_response(
        source: LiveCatalogSupplier,
        response: CatalogResponse,
    ) -> AggregateSourceReport:
        if response.supplier != source or response.mode != _MODE_BY_SUPPLIER[source]:
            return CatalogRegistry._unavailable_report(source)
        return AggregateSourceReport(
            supplier=source,
            mode=response.mode,
            state=response.state,
            freshness=response.freshness,
            error=response.error,
            item_count=len(response.items),
            partial=response.partial,
            omitted_count=response.omitted_count,
        )

    async def read_aggregate(self) -> AggregateCatalogResponse:
        """Read both sources concurrently and combine source-qualified rows only."""
        if not self.aggregate_available:
            raise CatalogSourceUnavailable("aggregate catalog is not configured")

        live_sources = tuple(source for source in self.sources if source in {"khommo", "vietshare"})
        raw_results = await asyncio.gather(
            *(self._readers[source].read_catalog() for source in live_sources),
            return_exceptions=True,
        )
        responses: dict[LiveCatalogSupplier, CatalogResponse | None] = {}
        reports: list[AggregateSourceReport] = []
        for source_value, result in zip(live_sources, raw_results, strict=True):
            source: LiveCatalogSupplier = source_value
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                responses[source] = None
                reports.append(self._unavailable_report(source))
                continue
            report = self._report_from_response(source, result)
            reports.append(report)
            responses[source] = result if report.state is not CatalogState.ERROR else None

        queues = []
        for source in live_sources:
            response = responses[source]
            queues.append(list(response.items) if response is not None else [])
        items = []
        while any(queues):
            for queue in queues:
                if queue:
                    items.append(queue.pop(0))

        degraded = any(
            report.partial or report.state in {CatalogState.STALE, CatalogState.ERROR}
            for report in reports
        )
        if items:
            state = AggregateCatalogState.PARTIAL if degraded else AggregateCatalogState.COMPLETE
        elif all(report.state is CatalogState.EMPTY for report in reports):
            state = AggregateCatalogState.EMPTY
        else:
            state = AggregateCatalogState.ERROR
        return AggregateCatalogResponse(
            state=state,
            items=tuple(items),
            sources=tuple(reports),
            partial=state is AggregateCatalogState.PARTIAL,
            omitted_count=sum(report.omitted_count for report in reports),
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
