import type { Money } from "./api";

export type LiveCatalogSupplier = "khommo" | "vietshare";

export interface CatalogCurationOfferWire {
  key: string;
  supplier: LiveCatalogSupplier;
  supplier_product_id: string;
  name: string;
  description: string;
  price: Money;
  available_quantity: number;
  assigned_listing_id: string | null;
  read_only: true;
}

export interface CatalogCurationListingWire {
  id: string;
  name: string;
  description: string;
  category: string | null;
  visible: boolean;
  sort_order: number;
  retail_price: Money | null;
  offer_keys: string[];
}

export interface CatalogCurationWorkspaceWire {
  revision: number;
  offers: CatalogCurationOfferWire[];
  listings: CatalogCurationListingWire[];
  unresolved_offer_count: number;
  source_partial: boolean;
  read_only: true;
  supplier_writes_enabled: false;
}

export interface CatalogCurationSaveWire {
  expected_revision: number;
  listings: CatalogCurationListingWire[];
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");
const endpoint = `${apiBaseUrl}/v1/admin/catalog-curation`;

export class CatalogCurationRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "CatalogCurationRequestError";
  }
}

async function responseError(response: Response): Promise<CatalogCurationRequestError> {
  let message = `Catalog curation request failed with ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.length > 0) {
      message = body.detail;
    }
  } catch {
    // Keep the sanitized status-only fallback.
  }
  return new CatalogCurationRequestError(response.status, message);
}

export async function fetchCatalogCuration(
  signal?: AbortSignal,
): Promise<CatalogCurationWorkspaceWire> {
  const response = await fetch(endpoint, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as CatalogCurationWorkspaceWire;
}

export async function saveCatalogCuration(
  body: CatalogCurationSaveWire,
): Promise<CatalogCurationWorkspaceWire> {
  const response = await fetch(endpoint, {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as CatalogCurationWorkspaceWire;
}
