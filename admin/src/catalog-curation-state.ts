import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CatalogSupplier, Money } from "./api";
import {
  CatalogCurationRequestError,
  type CatalogCurationListingWire,
  type CatalogCurationWorkspaceWire,
  fetchCatalogCuration,
  saveCatalogCuration,
} from "./catalog-curation-api";

export type LiveCatalogSupplier = Exclude<CatalogSupplier, "mock">;

export interface CatalogCurationOffer {
  key: string;
  supplier: LiveCatalogSupplier;
  supplierProductId: string;
  name: string;
  description: string;
  price: Money;
  availableQuantity: number;
  assignedListingId: string | null;
  readOnly: true;
}

export interface CatalogCurationListing {
  id: string;
  name: string;
  description: string;
  category: string | null;
  visible: boolean;
  sortOrder: number;
  retailPrice: Money | null;
  offerKeys: string[];
}

export type CatalogCurationListingPatch = Partial<
  Pick<
    CatalogCurationListing,
    "name" | "description" | "category" | "visible" | "retailPrice"
  >
>;

export type CatalogCurationSaveState =
  | { kind: "clean" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string }
  | { kind: "conflict"; message: string };

export type CatalogCurationState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "empty" }
  | {
      kind: "ready";
      revision: number;
      offers: CatalogCurationOffer[];
      listings: CatalogCurationListing[];
      sourcePartial: boolean;
      unresolvedOfferCount: number;
      save: CatalogCurationSaveState;
    };

export interface CatalogCurationProps {
  state: CatalogCurationState;
  onRetry: () => void;
  onCreateListing: (offerKey: string) => void;
  onAssignOffer: (offerKey: string, listingId: string | null) => void;
  onUpdateListing: (listingId: string, patch: CatalogCurationListingPatch) => void;
  onMoveListing: (listingId: string, direction: "up" | "down") => void;
  onDeleteListing: (listingId: string) => void;
  onSave: () => void;
  onReset: () => void;
}

export type CatalogCurationController = CatalogCurationProps;

function mapWorkspace(
  workspace: CatalogCurationWorkspaceWire,
  save: CatalogCurationSaveState,
): CatalogCurationState {
  if (workspace.offers.length === 0 && workspace.listings.length === 0) {
    return { kind: "empty" };
  }
  const assignments = new Map<string, string>();
  for (const listing of workspace.listings) {
    for (const key of listing.offer_keys) assignments.set(key, listing.id);
  }
  return {
    kind: "ready",
    revision: workspace.revision,
    offers: workspace.offers.map((offer) => ({
      key: offer.key,
      supplier: offer.supplier,
      supplierProductId: offer.supplier_product_id,
      name: offer.name,
      description: offer.description,
      price: offer.price,
      availableQuantity: offer.available_quantity,
      assignedListingId: assignments.get(offer.key) ?? null,
      readOnly: true,
    })),
    listings: workspace.listings
      .map((listing) => ({
        id: listing.id,
        name: listing.name,
        description: listing.description,
        category: listing.category,
        visible: listing.visible,
        sortOrder: listing.sort_order,
        retailPrice: listing.retail_price,
        offerKeys: [...listing.offer_keys],
      }))
      .sort((left, right) => left.sortOrder - right.sortOrder),
    sourcePartial: workspace.source_partial,
    unresolvedOfferCount: workspace.unresolved_offer_count,
    save,
  };
}

function toWire(listing: CatalogCurationListing): CatalogCurationListingWire {
  const category = listing.category?.trim() || null;
  return {
    id: listing.id,
    name: listing.name.trim(),
    description: listing.description.trim(),
    category,
    visible: listing.visible,
    sort_order: listing.sortOrder,
    retail_price: listing.retailPrice,
    offer_keys: [...listing.offerKeys],
  };
}

function createListingId(existing: CatalogCurationListing[]): string {
  const used = new Set(existing.map((listing) => listing.id));
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const candidate = `nyan-${Date.now().toString(36)}-${Math.random()
      .toString(36)
      .slice(2, 8)}`;
    if (!used.has(candidate)) return candidate;
  }
  throw new Error("Không thể tạo mã mục Nyan duy nhất.");
}

function validateDraft(listings: CatalogCurationListing[]): string | null {
  const keys = new Set<string>();
  for (const listing of listings) {
    if (!listing.name.trim() || !listing.description.trim()) {
      return "Tên và mô tả khách hàng không được để trống.";
    }
    if (listing.offerKeys.length === 0) {
      return "Mỗi mục Nyan phải giữ ít nhất một sản phẩm nguồn.";
    }
    if (listing.visible && listing.retailPrice === null) {
      return "Mục đang hiển thị phải có giá bán lẻ VND.";
    }
    if (
      listing.retailPrice !== null &&
      (!Number.isSafeInteger(listing.retailPrice.amount_minor) ||
        listing.retailPrice.amount_minor < 0 ||
        listing.retailPrice.currency !== "VND" ||
        listing.retailPrice.unit !== "minor")
    ) {
      return "Giá bán lẻ phải là số nguyên không âm theo đơn vị VND minor.";
    }
    for (const key of listing.offerKeys) {
      if (keys.has(key)) return "Một sản phẩm nguồn không thể thuộc hai mục Nyan.";
      keys.add(key);
    }
  }
  return null;
}

export function useCatalogCurationState(enabled: boolean): CatalogCurationController {
  const [requestVersion, setRequestVersion] = useState(0);
  const [state, setState] = useState<CatalogCurationState>({ kind: "loading" });
  const baseline = useRef<CatalogCurationWorkspaceWire | null>(null);

  const retry = useCallback(() => {
    setState({ kind: "loading" });
    setRequestVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setState({ kind: "loading" });
    void fetchCatalogCuration(controller.signal)
      .then((workspace) => {
        if (controller.signal.aborted) return;
        baseline.current = workspace;
        setState(mapWorkspace(workspace, { kind: "clean" }));
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          message: "Không đọc được cấu hình catalog cục bộ. Kiểm tra API và PostgreSQL.",
        });
      });
    return () => controller.abort();
  }, [enabled, requestVersion]);

  const updateReady = useCallback(
    (mutate: (current: Extract<CatalogCurationState, { kind: "ready" }>) => CatalogCurationListing[]) => {
      setState((current) => {
        if (current.kind !== "ready" || current.save.kind === "saving") return current;
        const listings = mutate(current);
        const assignments = new Map<string, string>();
        for (const listing of listings) {
          for (const key of listing.offerKeys) assignments.set(key, listing.id);
        }
        return {
          ...current,
          offers: current.offers.map((offer) => ({
            ...offer,
            assignedListingId: assignments.get(offer.key) ?? null,
          })),
          listings,
          save: { kind: "dirty" },
        };
      });
    },
    [],
  );

  const onCreateListing = useCallback(
    (offerKey: string) => {
      updateReady((current) => {
        const offer = current.offers.find(
          (candidate) => candidate.key === offerKey && candidate.assignedListingId === null,
        );
        if (!offer) return current.listings;
        return [
          ...current.listings,
          {
            id: createListingId(current.listings),
            name: offer.name,
            description: offer.description,
            category: null,
            visible: false,
            sortOrder: current.listings.length,
            retailPrice: null,
            offerKeys: [offer.key],
          },
        ];
      });
    },
    [updateReady],
  );

  const onAssignOffer = useCallback(
    (offerKey: string, listingId: string | null) => {
      setState((current) => {
        if (current.kind !== "ready" || current.save.kind === "saving") return current;
        const source = current.listings.find((listing) => listing.offerKeys.includes(offerKey));
        if (listingId === null && source?.offerKeys.length === 1) {
          return {
            ...current,
            save: {
              kind: "error",
              message: "Mỗi mục Nyan phải giữ ít nhất một sản phẩm nguồn.",
            },
          };
        }
        const listings = current.listings.map((listing) => {
          const without = listing.offerKeys.filter((key) => key !== offerKey);
          return listing.id === listingId
            ? { ...listing, offerKeys: [...without, offerKey] }
            : { ...listing, offerKeys: without };
        });
        const assignments = new Map<string, string>();
        for (const listing of listings) {
          for (const key of listing.offerKeys) assignments.set(key, listing.id);
        }
        return {
          ...current,
          offers: current.offers.map((offer) => ({
            ...offer,
            assignedListingId: assignments.get(offer.key) ?? null,
          })),
          listings,
          save: { kind: "dirty" },
        };
      });
    },
    [],
  );

  const onUpdateListing = useCallback(
    (listingId: string, patch: CatalogCurationListingPatch) => {
      updateReady((current) =>
        current.listings.map((listing) =>
          listing.id === listingId ? { ...listing, ...patch } : listing,
        ),
      );
    },
    [updateReady],
  );

  const onMoveListing = useCallback(
    (listingId: string, direction: "up" | "down") => {
      updateReady((current) => {
        const ordered = [...current.listings].sort((a, b) => a.sortOrder - b.sortOrder);
        const index = ordered.findIndex((listing) => listing.id === listingId);
        const target = direction === "up" ? index - 1 : index + 1;
        if (index < 0 || target < 0 || target >= ordered.length) return current.listings;
        [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
        return ordered.map((listing, sortOrder) => ({ ...listing, sortOrder }));
      });
    },
    [updateReady],
  );

  const onDeleteListing = useCallback(
    (listingId: string) => {
      updateReady((current) =>
        current.listings
          .filter((listing) => listing.id !== listingId)
          .sort((left, right) => left.sortOrder - right.sortOrder)
          .map((listing, sortOrder) => ({ ...listing, sortOrder })),
      );
    },
    [updateReady],
  );

  const onSave = useCallback(() => {
    if (state.kind !== "ready" || state.save.kind === "saving") return;
    const error = validateDraft(state.listings);
    if (error !== null) {
      setState({ ...state, save: { kind: "error", message: error } });
      return;
    }
    const request = {
      expected_revision: state.revision,
      listings: state.listings.map(toWire),
    };
    setState({ ...state, save: { kind: "saving" } });
    void saveCatalogCuration(request)
      .then((workspace) => {
        baseline.current = workspace;
        setState(mapWorkspace(workspace, { kind: "saved" }));
      })
      .catch((caught: unknown) => {
        setState((current) => {
          if (current.kind !== "ready") return current;
          if (caught instanceof CatalogCurationRequestError && caught.status === 409) {
            return {
              ...current,
              save: {
                kind: "conflict",
                message: "Catalog đã thay đổi ở phiên khác. Hãy hoàn tác để tải bản mới.",
              },
            };
          }
          return {
            ...current,
            save: { kind: "error", message: "Không lưu được catalog cục bộ." },
          };
        });
      });
  }, [state]);

  const onReset = useCallback(() => {
    setState((current) => {
      if (current.kind === "ready" && current.save.kind === "conflict") {
        queueMicrotask(retry);
        return { kind: "loading" };
      }
      return baseline.current === null
        ? { kind: "loading" }
        : mapWorkspace(baseline.current, { kind: "clean" });
    });
  }, [retry]);

  return useMemo(
    () => ({
      state,
      onRetry: retry,
      onCreateListing,
      onAssignOffer,
      onUpdateListing,
      onMoveListing,
      onDeleteListing,
      onSave,
      onReset,
    }),
    [
      state,
      retry,
      onCreateListing,
      onAssignOffer,
      onUpdateListing,
      onMoveListing,
      onDeleteListing,
      onSave,
      onReset,
    ],
  );
}
