import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.dataset.theme = "light";
  document.documentElement.style.colorScheme = "light";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const freshness = {
  status: "fresh",
  observed_at: "2026-09-20T00:00:00Z",
  evaluated_at: "2026-09-20T00:05:00Z",
  max_age_seconds: 900,
};

const catalogItem = {
  id: "mock-item",
  name: "Sản phẩm kiểm thử",
  description: "Dữ liệu tổng hợp từ backend",
  supplier: "mock",
  mode: "mock",
  read_only: true,
  price: { amount_minor: 42000, currency: "VND", unit: "minor" },
  available_quantity: 2,
  variants: [
    {
      id: "mock-variant",
      name: "Gói thử nghiệm",
      price: { amount_minor: 42000, currency: "VND", unit: "minor" },
      available_quantity: 2,
    },
  ],
};

const capabilities = {
  catalog_read: { status: "enabled", reason: null },
  catalog_detail: { status: "enabled", reason: null },
  purchase: { status: "disabled", reason: "Mock profile is read-only." },
  payment: { status: "disabled", reason: "Payments are disabled." },
  top_up: { status: "disabled", reason: "Top-up is disabled." },
  refund: { status: "disabled", reason: "Refunds are disabled." },
  delivery: { status: "disabled", reason: "Delivery is disabled." },
};

function freshCatalog(items: unknown[]) {
  return {
    supplier: "mock",
    mode: "mock",
    read_only: true,
    partial: false,
    omitted_count: 0,
    state: items.length === 0 ? "empty" : "fresh",
    freshness,
    items,
    error: null,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi(catalog: unknown, supplierCapabilities: unknown = capabilities) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    return Promise.resolve(
      url.endsWith("/v1/capabilities")
        ? jsonResponse(supplierCapabilities)
        : jsonResponse(catalog),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

test("shows explicit loading states while both API requests are pending", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

  render(<App />);

  expect(screen.getByText(/Đang tải catalog qua FastAPI/i)).toBeInTheDocument();
  expect(screen.getByText(/Đang đọc trạng thái supplier/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/Môi trường loading/i)).toBeInTheDocument();
});

test("renders generated-contract catalog and supplier truth without replacing API data", async () => {
  const fetchMock = stubApi(freshCatalog([catalogItem]));

  render(<App />);

  expect(await screen.findByText("Sản phẩm kiểm thử")).toBeInTheDocument();
  expect(screen.getByText("Dữ liệu tổng hợp từ backend")).toBeInTheDocument();
  expect(screen.getByText("42.000 VND · minor")).toBeInTheDocument();
  expect(screen.getByText(/Catalog API không công khai số dư supplier/i)).toBeInTheDocument();
  expect(screen.getAllByText(/MOCK/).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/chỉ chạy trên localhost/i)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalog",
    expect.objectContaining({ method: "GET" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/capabilities",
    expect.objectContaining({ method: "GET" }),
  );
});

test("renders KhoMMO live-read source while keeping every write boundary visibly locked", async () => {
  const liveItem = {
    ...catalogItem,
    id: "khommo-item",
    supplier: "khommo",
    mode: "khommo-readonly",
    read_only: true,
  };
  stubApi({
    supplier: "khommo",
    mode: "khommo-readonly",
    read_only: true,
    partial: true,
    omitted_count: 2,
    state: "fresh",
    freshness,
    items: [liveItem],
    error: null,
  });

  render(<App />);

  expect((await screen.findAllByText(/^khommo$/i)).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByLabelText(/Môi trường KHOMMO-READONLY/i)).toBeInTheDocument();
  expect(screen.getByText(/KhoMMO chỉ cho phép đọc catalog/i)).toBeInTheDocument();
  expect(screen.getByText(/Catalog đang hiển thị một phần/i)).toBeInTheDocument();
  expect(screen.getByText(/2 sản phẩm bị loại/i)).toBeInTheDocument();
  expect(screen.getAllByText("Đã khóa").length).toBeGreaterThanOrEqual(2);
});

test("filters injected catalog data without replacing the backend source", async () => {
  const secondItem = {
    ...catalogItem,
    id: "second-item",
    name: "Mục khác",
    description: "Fixture phụ",
  };
  stubApi(freshCatalog([catalogItem, secondItem]));

  render(<App />);

  expect(await screen.findByText("Sản phẩm kiểm thử")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: /Lọc catalog/i }), {
    target: { value: "fixture phụ" },
  });

  expect(screen.queryByText("Sản phẩm kiểm thử")).not.toBeInTheDocument();
  expect(screen.getByText("Mục khác")).toBeInTheDocument();
  expect(screen.getByText("1/2 sản phẩm")).toBeInTheDocument();
});

test("shows an explicit empty state from the catalog envelope", async () => {
  stubApi(freshCatalog([]));

  render(<App />);

  expect(await screen.findByText(/Catalog đang trống/i)).toBeInTheDocument();
  expect(screen.getByText(/Chưa có dữ liệu/i)).toBeInTheDocument();
});

test("shows a safe transport error and retries both read-only resources", async () => {
  let catalogRequests = 0;
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/v1/capabilities")) {
      return Promise.resolve(jsonResponse(capabilities));
    }

    catalogRequests += 1;
    return catalogRequests === 1
      ? Promise.resolve(new Response(null, { status: 503 }))
      : Promise.resolve(jsonResponse(freshCatalog([catalogItem])));
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(await screen.findByText(/Catalog không khả dụng/i)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: /Thử lại/i })[0]);

  expect(await screen.findByText("Sản phẩm kiểm thử")).toBeInTheDocument();
  expect(catalogRequests).toBe(2);
  expect(fetchMock).toHaveBeenCalledTimes(4);
});
