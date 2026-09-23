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

function sourceResponseFor(catalog: unknown) {
  const envelope = catalog as { supplier?: string; mode?: string };
  const supplier = envelope.supplier ?? "mock";
  const mode = envelope.mode ?? "mock";
  return {
    sources: [{ supplier, mode, read_only: true }],
    selection_required: false,
    aggregate_available: false,
  };
}

function stubApi(
  catalog: unknown,
  supplierCapabilities: unknown = capabilities,
  sources: unknown = sourceResponseFor(catalog),
) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const pathname = new URL(url, "http://localhost").pathname;
    if (pathname.endsWith("/v1/catalog/sources")) {
      return Promise.resolve(jsonResponse(sources));
    }
    if (pathname.endsWith("/v1/capabilities")) {
      return Promise.resolve(jsonResponse(supplierCapabilities));
    }
    return Promise.resolve(jsonResponse(catalog));
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
    "/api/v1/catalog?source=mock",
    expect.objectContaining({ method: "GET" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/capabilities?source=mock",
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

test("renders VietShare through the same API boundary with writes visibly locked", async () => {
  const liveItem = {
    ...catalogItem,
    id: "17",
    supplier: "vietshare",
    mode: "vietshare-readonly",
    read_only: true,
  };
  stubApi({
    supplier: "vietshare",
    mode: "vietshare-readonly",
    read_only: true,
    partial: false,
    omitted_count: 0,
    state: "fresh",
    freshness,
    items: [liveItem],
    error: null,
  });

  render(<App />);

  expect((await screen.findAllByText(/^vietshare$/i)).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByLabelText(/Môi trường VIETSHARE-READONLY/i)).toBeInTheDocument();
  expect(screen.getByText(/VietShare chỉ cho phép đọc catalog/i)).toBeInTheDocument();
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

test("switches explicitly between KhoMMO and VietShare through FastAPI", async () => {
  const sources = {
    sources: [
      { supplier: "khommo", mode: "khommo-readonly", read_only: true },
      { supplier: "vietshare", mode: "vietshare-readonly", read_only: true },
    ],
    selection_required: true,
    aggregate_available: false,
  };
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/v1/catalog/sources")) {
      return Promise.resolve(jsonResponse(sources));
    }
    if (url.pathname.endsWith("/v1/capabilities")) {
      return Promise.resolve(jsonResponse(capabilities));
    }
    const source = url.searchParams.get("source");
    const item = {
      ...catalogItem,
      id: `${source}-item`,
      name: source === "khommo" ? "Sản phẩm KhoMMO" : "Sản phẩm VietShare",
      supplier: source,
      mode: `${source}-readonly`,
    };
    return Promise.resolve(
      jsonResponse({
        supplier: source,
        mode: `${source}-readonly`,
        read_only: true,
        partial: false,
        omitted_count: 0,
        state: "fresh",
        freshness,
        items: [item],
        error: null,
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(await screen.findByText("Sản phẩm KhoMMO")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: /Chọn nguồn catalog/i }), {
    target: { value: "vietshare" },
  });

  expect(await screen.findByText("Sản phẩm VietShare")).toBeInTheDocument();
  expect(screen.queryByText("Sản phẩm KhoMMO")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalog?source=khommo",
    expect.objectContaining({ method: "GET" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalog?source=vietshare",
    expect.objectContaining({ method: "GET" }),
  );
});

test("selects the combined read-only view while preserving duplicate source identities", async () => {
  const sources = {
    sources: [
      { supplier: "khommo", mode: "khommo-readonly", read_only: true },
      { supplier: "vietshare", mode: "vietshare-readonly", read_only: true },
    ],
    selection_required: true,
    aggregate_available: true,
  };
  const khommoItem = {
    ...catalogItem,
    id: "shared-id",
    name: "Sản phẩm KhoMMO tổng hợp",
    supplier: "khommo",
    mode: "khommo-readonly",
  };
  const vietshareItem = {
    ...catalogItem,
    id: "shared-id",
    name: "Sản phẩm VietShare tổng hợp",
    supplier: "vietshare",
    mode: "vietshare-readonly",
  };
  const aggregate = {
    supplier: "aggregate",
    mode: "multi-readonly",
    state: "complete",
    items: [khommoItem, vietshareItem],
    sources: [
      {
        supplier: "khommo",
        mode: "khommo-readonly",
        state: "fresh",
        freshness,
        error: null,
        item_count: 1,
        partial: false,
        omitted_count: 0,
      },
      {
        supplier: "vietshare",
        mode: "vietshare-readonly",
        state: "fresh",
        freshness,
        error: null,
        item_count: 1,
        partial: false,
        omitted_count: 0,
      },
    ],
    read_only: true,
    partial: false,
    omitted_count: 0,
  };
  const fetchMock = stubApi(aggregate, capabilities, sources);

  render(<App />);

  expect(await screen.findByText("Sản phẩm KhoMMO tổng hợp")).toBeInTheDocument();
  expect(screen.getByText("Sản phẩm VietShare tổng hợp")).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: /Chọn nguồn catalog/i })).toHaveValue("all");
  expect(screen.getAllByText(/KhoMMO \+ VietShare/i).length).toBeGreaterThanOrEqual(1);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalog?source=all",
    expect.objectContaining({ method: "GET" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/capabilities?source=all",
    expect.objectContaining({ method: "GET" }),
  );
});

test("keeps usable aggregate rows while identifying a failed source safely", async () => {
  const khommoItem = {
    ...catalogItem,
    id: "khommo-only",
    name: "KhoMMO vẫn khả dụng",
    supplier: "khommo",
    mode: "khommo-readonly",
  };
  const aggregate = {
    supplier: "aggregate",
    mode: "multi-readonly",
    state: "partial",
    items: [khommoItem],
    sources: [
      {
        supplier: "khommo",
        mode: "khommo-readonly",
        state: "fresh",
        freshness,
        error: null,
        item_count: 1,
        partial: false,
        omitted_count: 0,
      },
      {
        supplier: "vietshare",
        mode: "vietshare-readonly",
        state: "error",
        freshness: null,
        error: {
          code: "source_unavailable",
          message: "private token=NEVER-PRINT",
          retryable: true,
        },
        item_count: 0,
        partial: false,
        omitted_count: 0,
      },
    ],
    read_only: true,
    partial: true,
    omitted_count: 0,
  };
  stubApi(aggregate, capabilities, {
    sources: [
      { supplier: "khommo", mode: "khommo-readonly", read_only: true },
      { supplier: "vietshare", mode: "vietshare-readonly", read_only: true },
    ],
    selection_required: true,
    aggregate_available: true,
  });

  render(<App />);

  expect(await screen.findByText("KhoMMO vẫn khả dụng")).toBeInTheDocument();
  expect(screen.getByText(/Một hoặc nhiều nguồn chưa đầy đủ/i)).toBeInTheDocument();
  expect(screen.getByText(/vietshare: nguồn hiện không khả dụng/i)).toBeInTheDocument();
  expect(screen.queryByText(/NEVER-PRINT/i)).not.toBeInTheDocument();
});

test("identifies a fresh partial source and its exact aggregate omissions", async () => {
  const khommoItem = {
    ...catalogItem,
    id: "khommo-partial",
    supplier: "khommo",
    mode: "khommo-readonly",
  };
  const vietshareItem = {
    ...catalogItem,
    id: "vietshare-fresh",
    supplier: "vietshare",
    mode: "vietshare-readonly",
  };
  stubApi(
    {
      supplier: "aggregate",
      mode: "multi-readonly",
      state: "partial",
      items: [khommoItem, vietshareItem],
      sources: [
        {
          supplier: "khommo",
          mode: "khommo-readonly",
          state: "fresh",
          freshness,
          error: null,
          item_count: 1,
          partial: true,
          omitted_count: 3,
        },
        {
          supplier: "vietshare",
          mode: "vietshare-readonly",
          state: "fresh",
          freshness,
          error: null,
          item_count: 1,
          partial: false,
          omitted_count: 0,
        },
      ],
      read_only: true,
      partial: true,
      omitted_count: 3,
    },
    capabilities,
    {
      sources: [
        { supplier: "khommo", mode: "khommo-readonly", read_only: true },
        { supplier: "vietshare", mode: "vietshare-readonly", read_only: true },
      ],
      selection_required: true,
      aggregate_available: true,
    },
  );

  render(<App />);

  expect(await screen.findByText(/Trạng thái từng nguồn/i)).toBeInTheDocument();
  expect(
    screen.getByText(/KhoMMO: dữ liệu mới · 1 sản phẩm · 3 sản phẩm bị loại/i),
  ).toBeInTheDocument();
  expect(screen.getByText(/VietShare: dữ liệu mới · 1 sản phẩm/i)).toBeInTheDocument();
});

test("preserves stale and partial evidence for the same aggregate source", async () => {
  const staleFreshness = {
    ...freshness,
    status: "stale",
    evaluated_at: "2026-09-20T01:00:00Z",
  };
  const khommoItem = {
    ...catalogItem,
    id: "khommo-stale-partial",
    supplier: "khommo",
    mode: "khommo-readonly",
  };
  const vietshareItem = {
    ...catalogItem,
    id: "vietshare-fresh",
    supplier: "vietshare",
    mode: "vietshare-readonly",
  };
  stubApi(
    {
      supplier: "aggregate",
      mode: "multi-readonly",
      state: "partial",
      items: [khommoItem, vietshareItem],
      sources: [
        {
          supplier: "khommo",
          mode: "khommo-readonly",
          state: "stale",
          freshness: staleFreshness,
          error: {
            code: "source_unavailable",
            message: "private token=NEVER-PRINT",
            retryable: true,
          },
          item_count: 1,
          partial: true,
          omitted_count: 2,
        },
        {
          supplier: "vietshare",
          mode: "vietshare-readonly",
          state: "fresh",
          freshness,
          error: null,
          item_count: 1,
          partial: false,
          omitted_count: 0,
        },
      ],
      read_only: true,
      partial: true,
      omitted_count: 2,
    },
    capabilities,
    {
      sources: [
        { supplier: "khommo", mode: "khommo-readonly", read_only: true },
        { supplier: "vietshare", mode: "vietshare-readonly", read_only: true },
      ],
      selection_required: true,
      aggregate_available: true,
    },
  );

  render(<App />);

  expect(
    await screen.findByText(/KhoMMO: cache đã cũ · 1 sản phẩm · 2 sản phẩm bị loại/i),
  ).toBeInTheDocument();
  expect(screen.getByText(/VietShare: dữ liệu mới · 1 sản phẩm/i)).toBeInTheDocument();
  expect(screen.queryByText(/NEVER-PRINT/i)).not.toBeInTheDocument();
});

test("keeps successful-empty and failed source evidence when aggregate has no rows", async () => {
  stubApi(
    {
      supplier: "aggregate",
      mode: "multi-readonly",
      state: "error",
      items: [],
      sources: [
        {
          supplier: "khommo",
          mode: "khommo-readonly",
          state: "empty",
          freshness,
          error: null,
          item_count: 0,
          partial: false,
          omitted_count: 0,
        },
        {
          supplier: "vietshare",
          mode: "vietshare-readonly",
          state: "error",
          freshness: null,
          error: {
            code: "source_unavailable",
            message: "private token=NEVER-PRINT",
            retryable: true,
          },
          item_count: 0,
          partial: false,
          omitted_count: 0,
        },
      ],
      read_only: true,
      partial: false,
      omitted_count: 0,
    },
    capabilities,
    {
      sources: [
        { supplier: "khommo", mode: "khommo-readonly", read_only: true },
        { supplier: "vietshare", mode: "vietshare-readonly", read_only: true },
      ],
      selection_required: true,
      aggregate_available: true,
    },
  );

  render(<App />);

  expect(await screen.findByText(/Không đọc được catalog/i)).toBeInTheDocument();
  expect(screen.getByText(/KhoMMO: phản hồi thành công · catalog trống/i)).toBeInTheDocument();
  expect(
    screen.getByText(/VietShare: không khả dụng · không suy đoán sản phẩm bị thiếu/i),
  ).toBeInTheDocument();
  expect(screen.queryByText(/NEVER-PRINT/i)).not.toBeInTheDocument();
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
    const pathname = new URL(url, "http://localhost").pathname;
    if (pathname.endsWith("/v1/catalog/sources")) {
      return Promise.resolve(jsonResponse(sourceResponseFor(freshCatalog([catalogItem]))));
    }
    if (pathname.endsWith("/v1/capabilities")) {
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
  expect(fetchMock).toHaveBeenCalledTimes(6);
});
