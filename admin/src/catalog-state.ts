import { useCallback, useEffect, useState } from "react";

import { type CatalogItem, fetchCatalog } from "./api";

export type CatalogViewState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "empty" }
  | { kind: "success"; items: CatalogItem[] };

export interface CatalogVisibilityProps {
  state: CatalogViewState;
  onRetry: () => void;
}

export interface CatalogStateController {
  state: CatalogViewState;
  retry: () => void;
}

export function useCatalogState(): CatalogStateController {
  const [requestVersion, setRequestVersion] = useState(0);
  const [state, setState] = useState<CatalogViewState>({ kind: "loading" });

  const retry = useCallback(() => {
    setState({ kind: "loading" });
    setRequestVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    void fetchCatalog(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) {
          return;
        }
        setState(
          result.items.length === 0
            ? { kind: "empty" }
            : { kind: "success", items: result.items },
        );
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : "Lỗi không xác định";
          setState({ kind: "error", message });
        }
      });

    return () => controller.abort();
  }, [requestVersion]);

  return { state, retry };
}
