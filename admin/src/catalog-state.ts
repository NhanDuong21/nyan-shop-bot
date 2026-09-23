import { useCallback, useEffect, useState } from "react";

import {
  type CatalogError,
  type CatalogFreshness,
  type CatalogItem,
  type CatalogResponse,
  type CatalogSelection,
  type CatalogSourceOption,
  type CatalogViewMode,
  type CatalogViewSupplier,
  fetchCapabilities,
  fetchCatalog,
  fetchCatalogSources,
  type SupplierCapabilities,
} from "./api";

export type CatalogPanelState =
  | { kind: "loading" }
  | { kind: "error"; message: string; retryable: boolean }
  | { kind: "empty"; freshness: CatalogFreshness | null }
  | {
      kind: "success";
      items: CatalogItem[];
      freshness: CatalogFreshness | null;
      warning: CatalogError | null;
      warningTitle?: string;
      partial: boolean;
      omittedCount: number;
    };

export type SupplierPanelState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      supplier: CatalogViewSupplier;
      mode: CatalogViewMode;
      readOnly: true;
      currencies: string[];
      balance: {
        kind: "unsupported";
        reason: string;
      };
      capabilities: SupplierCapabilities;
    };

export type CatalogViewState = CatalogPanelState;

export interface AdminDashboardState {
  catalog: CatalogPanelState;
  supplier: SupplierPanelState;
}

export interface CatalogVisibilityProps {
  state: CatalogViewState;
  onRetry: () => void;
}

export interface AdminDashboardProps {
  state: AdminDashboardState;
  onRetry: () => void;
}

export interface CatalogStateController {
  state: AdminDashboardState;
  sources: CatalogSourceOption[];
  aggregateAvailable: boolean;
  selectedSource: CatalogSelection | null;
  selectSource: (source: CatalogSelection) => void;
  retry: () => void;
}

function mapCatalogState(response: CatalogResponse): CatalogPanelState {
  if (response.mode === "multi-readonly") {
    if (response.state === "empty") {
      return { kind: "empty", freshness: null };
    }
    if (response.state === "error") {
      return {
        kind: "error",
        message: "KhoMMO và VietShare đều không trả về catalog dùng được lúc này.",
        retryable: response.sources.some((source) => source.error?.retryable === true),
      };
    }
    const degraded = response.sources.filter(
      (source) => source.state === "stale" || source.state === "error",
    );
    const warning =
      degraded.length === 0
        ? null
        : {
            code: "source_unavailable" as const,
            message: degraded
              .map((source) =>
                source.state === "error"
                  ? `${source.supplier}: nguồn hiện không khả dụng.`
                  : `${source.supplier}: đang hiển thị dữ liệu cache đã cũ.`,
              )
              .join(" "),
            retryable: degraded.some((source) => source.error?.retryable === true),
          };
    return {
      kind: "success",
      items: response.items,
      freshness: null,
      warning,
      warningTitle: "Một hoặc nhiều nguồn chưa đầy đủ",
      partial: response.partial,
      omittedCount: response.omitted_count,
    };
  }
  switch (response.state) {
    case "fresh":
      return {
        kind: "success",
        items: response.items,
        freshness: response.freshness,
        warning: null,
        partial: response.partial,
        omittedCount: response.omitted_count,
      };
    case "stale":
      return {
        kind: "success",
        items: response.items,
        freshness: response.freshness,
        warning: response.error,
        partial: response.partial,
        omittedCount: response.omitted_count,
      };
    case "empty":
      return { kind: "empty", freshness: response.freshness };
    case "error":
      return {
        kind: "error",
        message: response.error.message,
        retryable: response.error.retryable,
      };
  }
}

function catalogCurrencies(response: CatalogResponse | null): string[] {
  if (response === null || response.state === "error") {
    return [];
  }

  const currencies = response.items.flatMap((item) => [
    item.price.currency,
    ...item.variants.map((variant) => variant.price.currency),
  ]);
  return [...new Set(currencies)].sort();
}

function requestFailure(resource: string): string {
  return `${resource} không khả dụng. Kiểm tra backend localhost rồi thử lại.`;
}

export function useCatalogState(): CatalogStateController {
  const [requestVersion, setRequestVersion] = useState(0);
  const [sources, setSources] = useState<CatalogSourceOption[]>([]);
  const [aggregateAvailable, setAggregateAvailable] = useState(false);
  const [selectedSource, setSelectedSource] = useState<CatalogSelection | null>(null);
  const [state, setState] = useState<AdminDashboardState>({
    catalog: { kind: "loading" },
    supplier: { kind: "loading" },
  });

  const retry = useCallback(() => {
    setState({
      catalog: { kind: "loading" },
      supplier: { kind: "loading" },
    });
    setRequestVersion((version) => version + 1);
  }, []);

  const selectSource = useCallback(
    (source: CatalogSelection) => {
      if (
        (source === "all" && !aggregateAvailable) ||
        (source !== "all" && !sources.some((option) => option.supplier === source))
      ) {
        return;
      }
      setState({
        catalog: { kind: "loading" },
        supplier: { kind: "loading" },
      });
      setSelectedSource(source);
    },
    [aggregateAvailable, sources],
  );

  useEffect(() => {
    const controller = new AbortController();

    void fetchCatalogSources(controller.signal)
      .then((response) => {
        if (controller.signal.aborted) {
          return;
        }
        setSources(response.sources);
        const canAggregate = response.aggregate_available === true;
        setAggregateAvailable(canAggregate);
        setSelectedSource((current) => {
          if (current === "all" && canAggregate) {
            return current;
          }
          if (current !== null && response.sources.some((item) => item.supplier === current)) {
            return current;
          }
          if (canAggregate) {
            return "all";
          }
          return response.sources[0]?.supplier ?? null;
        });
      })
      .catch(() => {
        if (controller.signal.aborted) {
          return;
        }
        setSources([]);
        setAggregateAvailable(false);
        setSelectedSource(null);
        setState({
          catalog: {
            kind: "error",
            message: requestFailure("Danh sách nguồn catalog"),
            retryable: true,
          },
          supplier: {
            kind: "error",
            message: requestFailure("Danh sách nguồn catalog"),
          },
        });
      });

    return () => controller.abort();
  }, [requestVersion]);

  useEffect(() => {
    if (selectedSource === null) {
      return;
    }
    const controller = new AbortController();

    void Promise.allSettled([
      fetchCatalog(controller.signal, selectedSource),
      fetchCapabilities(controller.signal, selectedSource),
    ]).then(([catalogResult, capabilitiesResult]) => {
      if (controller.signal.aborted) {
        return;
      }

      const catalogResponse =
        catalogResult.status === "fulfilled" ? catalogResult.value : null;

      setState({
        catalog:
          catalogResponse === null
            ? {
                kind: "error",
                message: requestFailure("Catalog"),
                retryable: true,
              }
            : mapCatalogState(catalogResponse),
        supplier:
          capabilitiesResult.status === "fulfilled" && catalogResponse !== null
            ? {
                kind: "ready",
                supplier: catalogResponse.supplier,
                mode: catalogResponse.mode,
                readOnly: catalogResponse.read_only,
                currencies: catalogCurrencies(catalogResponse),
                balance: {
                  kind: "unsupported",
                  reason: "Catalog API không công khai số dư supplier.",
                },
                capabilities: capabilitiesResult.value,
              }
            : {
                kind: "error",
                message: requestFailure("Trạng thái supplier"),
              },
      });
    });

    return () => controller.abort();
  }, [requestVersion, selectedSource]);

  return {
    state,
    sources,
    aggregateAvailable,
    selectedSource,
    selectSource,
    retry,
  };
}
