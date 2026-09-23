export interface Money {
  amount_minor: number;
  currency: string;
  unit: "minor";
}

export type CatalogSupplier = "mock" | "khommo" | "vietshare";
export type CatalogMode = "mock" | "khommo-readonly" | "vietshare-readonly";
export type CatalogSelection = CatalogSupplier | "all";
export type CatalogViewSupplier = CatalogSupplier | "aggregate";
export type CatalogViewMode = CatalogMode | "multi-readonly";

export interface CatalogSourceOption {
  supplier: CatalogSupplier;
  mode: CatalogMode;
  read_only: true;
}

export interface CatalogSourcesResponse {
  sources: CatalogSourceOption[];
  selection_required: boolean;
  aggregate_available: boolean;
}

export interface CatalogVariant {
  id: string;
  name: string;
  price: Money;
  available_quantity: number;
}

export interface CatalogItem {
  id: string;
  name: string;
  description: string;
  supplier: CatalogSupplier;
  mode: CatalogMode;
  read_only: true;
  price: Money;
  available_quantity: number;
  variants: CatalogVariant[];
}

export interface CatalogFreshness {
  status: "fresh" | "stale";
  observed_at: string;
  evaluated_at: string;
  max_age_seconds: number;
}

export interface CatalogError {
  code: "source_unavailable" | "unsupported";
  message: string;
  retryable: boolean;
}

interface SourceCatalogEnvelopeBase {
  supplier: CatalogSupplier;
  mode: CatalogMode;
  read_only: true;
  partial: boolean;
  omitted_count: number;
}

export type SourceCatalogResponse =
  | (SourceCatalogEnvelopeBase & {
      state: "fresh";
      freshness: CatalogFreshness;
      items: CatalogItem[];
      error: null;
    })
  | (SourceCatalogEnvelopeBase & {
      state: "stale";
      freshness: CatalogFreshness;
      items: CatalogItem[];
      error: CatalogError;
    })
  | (SourceCatalogEnvelopeBase & {
      state: "empty";
      freshness: CatalogFreshness;
      items: [];
      error: null;
    })
  | (SourceCatalogEnvelopeBase & {
      state: "error";
      freshness: null;
      items: [];
      error: CatalogError;
    });

export interface AggregateSourceReport {
  supplier: "khommo" | "vietshare";
  mode: "khommo-readonly" | "vietshare-readonly";
  state: "fresh" | "stale" | "empty" | "error";
  freshness: CatalogFreshness | null;
  error: CatalogError | null;
  item_count: number;
  partial: boolean;
  omitted_count: number;
}

export interface AggregateCatalogResponse {
  supplier: "aggregate";
  mode: "multi-readonly";
  state: "complete" | "partial" | "empty" | "error";
  items: CatalogItem[];
  sources: AggregateSourceReport[];
  read_only: true;
  partial: boolean;
  omitted_count: number;
}

export type CatalogResponse = SourceCatalogResponse | AggregateCatalogResponse;

export interface Capability {
  status: "enabled" | "disabled" | "unsupported";
  reason: string | null;
}

export interface SupplierCapabilities {
  catalog_read: Capability;
  catalog_detail: Capability;
  purchase: Capability;
  payment: Capability;
  top_up: Capability;
  refund: Capability;
  delivery: Capability;
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

function sourceUrl(path: string, source?: CatalogSelection): string {
  if (source === undefined) {
    return `${apiBaseUrl}${path}`;
  }
  const query = new URLSearchParams({ source });
  return `${apiBaseUrl}${path}?${query.toString()}`;
}

export async function fetchCatalogSources(
  signal?: AbortSignal,
): Promise<CatalogSourcesResponse> {
  const response = await fetch(`${apiBaseUrl}/v1/catalog/sources`, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Catalog sources request failed with ${response.status}`);
  }

  return (await response.json()) as CatalogSourcesResponse;
}

export async function fetchCatalog(
  signal?: AbortSignal,
  source?: CatalogSelection,
): Promise<CatalogResponse> {
  const response = await fetch(sourceUrl("/v1/catalog", source), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Catalog request failed with ${response.status}`);
  }

  return (await response.json()) as CatalogResponse;
}

export async function fetchCapabilities(
  signal?: AbortSignal,
  source?: CatalogSelection,
): Promise<SupplierCapabilities> {
  const response = await fetch(sourceUrl("/v1/capabilities", source), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Capabilities request failed with ${response.status}`);
  }

  return (await response.json()) as SupplierCapabilities;
}
