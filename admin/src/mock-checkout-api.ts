import type { Money } from "./api";

export interface MockVariant {
  id: string;
  name: string;
  price: Money;
  available_quantity: number;
}

export interface MockProduct {
  id: string;
  name: string;
  description: string;
  variants: MockVariant[];
}

export interface MockCatalog {
  mode: "MOCK";
  payment_mode: "disabled";
  items: MockProduct[];
}

export interface MockOrder {
  intent_id: string;
  product_id: string;
  variant_id: string;
  quantity: number;
  unit_price: Money;
  max_unit_price: Money;
  total_price: Money;
  purchase_state: "PREPARED" | "DISPATCHING" | "SUCCEEDED" | "FAILED_SAFE" | "UNKNOWN" | "RECONCILING";
  failure_code: string | null;
}

export type MockScenario = "success" | "failed_safe" | "unknown";
export type MockEvidence = "unresolved" | "confirmed_success" | "confirmed_out_of_stock";

const base = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

async function request<T>(token: string, path: string, body?: object): Promise<T> {
  const response = await fetch(`${base}/v1/mock-checkout${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(
      response.status === 401
        ? "Khóa demo không hợp lệ."
        : response.status === 403 || response.status === 503
          ? "Checkout MOCK chỉ khả dụng trên API local đúng cấu hình."
          : `Thao tác MOCK thất bại (${response.status}). Kiểm tra lịch sử trước khi thử lại.`,
    );
  }
  return (await response.json()) as T;
}

export const fetchMockCatalog = (token: string) => request<MockCatalog>(token, "/catalog");
export const fetchMockOrders = (token: string) => request<MockOrder[]>(token, "/orders");

export function placeMockOrder(
  token: string,
  input: {
    product_id: string;
    variant_id: string;
    quantity: number;
    idempotency_key: string;
    max_unit_price: Money;
    scenario: MockScenario;
  },
) {
  return request<MockOrder>(token, "/orders", input);
}

export function reconcileMockOrder(token: string, intentId: string, evidence: MockEvidence) {
  return request<MockOrder>(token, `/orders/${encodeURIComponent(intentId)}/reconcile`, {
    evidence,
  });
}
