import { useCallback, useEffect, useState } from "react";

import {
  type CatalogError,
  type CatalogFreshness,
  type CatalogItem,
  type CatalogResponse,
  fetchCapabilities,
  fetchCatalog,
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
    };

export type SupplierPanelState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      supplier: "mock";
      mode: "mock";
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
      };
    case "stale":
      return {
        kind: "success",
        items: response.items,
        freshness: response.freshness,
        warning: response.error,
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

  useEffect(() => {
    const controller = new AbortController();

    void Promise.allSettled([
      fetchCatalog(controller.signal),
      fetchCapabilities(controller.signal),
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
          capabilitiesResult.status === "fulfilled"
            ? {
                kind: "ready",
                supplier: "mock",
                mode: "mock",
                currencies: catalogCurrencies(catalogResponse),
                balance: {
                  kind: "unsupported",
                  reason: "Backend mock không cung cấp số dư supplier.",
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
  }, [requestVersion]);

  return { state, retry };
}
