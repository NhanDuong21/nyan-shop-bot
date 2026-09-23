import { useCallback, useEffect, useState } from "react";

import {
  type CatalogError,
  type CatalogFreshness,
  type CatalogItem,
  type CatalogMode,
  type CatalogResponse,
  type CatalogSourceOption,
  type CatalogSupplier,
  fetchCapabilities,
  fetchCatalog,
  fetchCatalogSources,
  type SupplierCapabilities,
} from "./api";

export type CatalogPanelState =
  | { kind: "loading" }
  | { kind: "error"; message: string; retryable: boolean }
  | { kind: "empty"; freshness: CatalogFreshness }
  | {
      kind: "success";
      items: CatalogItem[];
      freshness: CatalogFreshness;
      warning: CatalogError | null;
      partial: boolean;
      omittedCount: number;
    };

export type SupplierPanelState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      supplier: CatalogSupplier;
      mode: CatalogMode;
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
  selectedSource: CatalogSupplier | null;
  selectSource: (source: CatalogSupplier) => void;
  retry: () => void;
}

function mapCatalogState(response: CatalogResponse): CatalogPanelState {
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
  const [selectedSource, setSelectedSource] = useState<CatalogSupplier | null>(null);
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
    (source: CatalogSupplier) => {
      if (!sources.some((option) => option.supplier === source)) {
        return;
      }
      setState({
        catalog: { kind: "loading" },
        supplier: { kind: "loading" },
      });
      setSelectedSource(source);
    },
    [sources],
  );

  useEffect(() => {
    const controller = new AbortController();

    void fetchCatalogSources(controller.signal)
      .then((response) => {
        if (controller.signal.aborted) {
          return;
        }
        setSources(response.sources);
        setSelectedSource((current) => {
          if (current !== null && response.sources.some((item) => item.supplier === current)) {
            return current;
          }
          return response.sources[0]?.supplier ?? null;
        });
      })
      .catch(() => {
        if (controller.signal.aborted) {
          return;
        }
        setSources([]);
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

  return { state, sources, selectedSource, selectSource, retry };
}
