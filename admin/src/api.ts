export interface Money {
  amount_minor: number;
  currency: string;
  unit: "minor";
}

export type CatalogSupplier = "mock" | "khommo";
export type CatalogMode = "mock" | "khommo-readonly";

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

interface CatalogEnvelopeBase {
  supplier: CatalogSupplier;
  mode: CatalogMode;
  read_only: true;
  partial: boolean;
  omitted_count: number;
}

export type CatalogResponse =
  | (CatalogEnvelopeBase & {
      state: "fresh";
      freshness: CatalogFreshness;
      items: CatalogItem[];
      error: null;
    })
  | (CatalogEnvelopeBase & {
      state: "stale";
      freshness: CatalogFreshness;
      items: CatalogItem[];
      error: CatalogError;
    })
  | (CatalogEnvelopeBase & {
      state: "empty";
      freshness: CatalogFreshness;
      items: [];
      error: null;
    })
  | (CatalogEnvelopeBase & {
      state: "error";
      freshness: null;
      items: [];
      error: CatalogError;
    });

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

export async function fetchCatalog(signal?: AbortSignal): Promise<CatalogResponse> {
  const response = await fetch(`${apiBaseUrl}/v1/catalog`, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Catalog request failed with ${response.status}`);
  }

  return (await response.json()) as CatalogResponse;
}

export async function fetchCapabilities(signal?: AbortSignal): Promise<SupplierCapabilities> {
  const response = await fetch(`${apiBaseUrl}/v1/capabilities`, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Capabilities request failed with ${response.status}`);
  }

  return (await response.json()) as SupplierCapabilities;
}
