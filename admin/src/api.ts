export interface Money {
  amount_minor: number;
  currency: "VND";
}

export interface CatalogItem {
  id: string;
  name: string;
  description: string;
  supplier: "mock";
  mode: "mock";
  price: Money;
  available_quantity: number;
}

export interface CatalogResponse {
  mode: "mock";
  items: CatalogItem[];
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
