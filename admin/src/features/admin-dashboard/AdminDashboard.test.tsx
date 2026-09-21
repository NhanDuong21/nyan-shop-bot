import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { AdminDashboardState } from "../../catalog-state";
import { AdminDashboard } from "./AdminDashboard";

afterEach(cleanup);

const freshness = {
  status: "fresh" as const,
  observed_at: "2026-09-20T00:00:00Z",
  evaluated_at: "2026-09-20T00:05:00Z",
  max_age_seconds: 900,
};

const item = {
  id: "synthetic-item",
  name: "Sản phẩm tổng hợp",
  description: "Chỉ dùng cho kiểm thử",
  supplier: "mock" as const,
  mode: "mock" as const,
  price: { amount_minor: 1250, currency: "USD", unit: "minor" as const },
  available_quantity: 4,
  variants: [
    {
      id: "synthetic-variant",
      name: "Biến thể tổng hợp",
      price: { amount_minor: 1250, currency: "USD", unit: "minor" as const },
      available_quantity: 4,
    },
  ],
};

const capabilities = {
  catalog_read: { status: "enabled" as const, reason: null },
  catalog_detail: { status: "enabled" as const, reason: null },
  purchase: { status: "disabled" as const, reason: "Read-only." },
  payment: { status: "disabled" as const, reason: "Disabled." },
  top_up: { status: "disabled" as const, reason: "Disabled." },
  refund: { status: "disabled" as const, reason: "Disabled." },
  delivery: { status: "disabled" as const, reason: "Disabled." },
};

function supplierReady(): AdminDashboardState["supplier"] {
  return {
    kind: "ready",
    supplier: "mock",
    mode: "mock",
    currencies: ["USD"],
    balance: {
      kind: "unsupported",
      reason: "Backend mock không cung cấp số dư supplier.",
    },
    capabilities,
  };
}

test("announces independent catalog and supplier loading states", () => {
  render(
    <AdminDashboard
      state={{ catalog: { kind: "loading" }, supplier: { kind: "loading" } }}
      onRetry={vi.fn()}
    />,
  );

  expect(screen.getByText(/Đang tải catalog mock/i)).toBeInTheDocument();
  expect(screen.getByText(/Đang đọc trạng thái supplier/i)).toBeInTheDocument();
});

test("shows backend envelope errors and exposes retry only when allowed", () => {
  const onRetry = vi.fn();
  render(
    <AdminDashboard
      state={{
        catalog: {
          kind: "error",
          message: "Nguồn mock tạm thời không khả dụng.",
          retryable: true,
        },
        supplier: supplierReady(),
      }}
      onRetry={onRetry}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /Thử lại/i }));
  expect(onRetry).toHaveBeenCalledOnce();
  expect(screen.getByText(/Nguồn mock tạm thời/i)).toBeInTheDocument();
});

test("keeps supplier failures distinct from a usable catalog", () => {
  render(
    <AdminDashboard
      state={{
        catalog: { kind: "success", items: [item], freshness, warning: null },
        supplier: { kind: "error", message: "Trạng thái supplier không khả dụng." },
      }}
      onRetry={vi.fn()}
    />,
  );

  expect(screen.getByText("Sản phẩm tổng hợp")).toBeInTheDocument();
  expect(screen.getByText(/Trạng thái supplier không khả dụng/i)).toBeInTheDocument();
});

test("renders stale cached data, explicit minor money, and unsupported balance honestly", () => {
  render(
    <AdminDashboard
      state={{
        catalog: {
          kind: "success",
          items: [item],
          freshness: { ...freshness, status: "stale" },
          warning: {
            code: "source_unavailable",
            message: "Làm mới thất bại; đang dùng cache.",
            retryable: true,
          },
        },
        supplier: supplierReady(),
      }}
      onRetry={vi.fn()}
    />,
  );

  expect(screen.getByText(/dữ liệu cache đã cũ/i)).toBeInTheDocument();
  expect(screen.getByText("1.250 USD · minor")).toBeInTheDocument();
  expect(screen.getByText("USD")).toBeInTheDocument();
  expect(screen.getByText(/không cung cấp số dư supplier/i)).toBeInTheDocument();
  expect(screen.getByText("MOCK · READ-ONLY")).toBeInTheDocument();
  expect(screen.getAllByText("Đã khóa").length).toBeGreaterThanOrEqual(2);
});

test("renders empty and filtered-empty states without inventing catalog data", () => {
  const { rerender } = render(
    <AdminDashboard
      state={{ catalog: { kind: "empty", freshness }, supplier: supplierReady() }}
      onRetry={vi.fn()}
    />,
  );

  expect(screen.getByText(/Catalog mock đang trống/i)).toBeInTheDocument();

  rerender(
    <AdminDashboard
      state={{
        catalog: { kind: "success", items: [item], freshness, warning: null },
        supplier: supplierReady(),
      }}
      onRetry={vi.fn()}
    />,
  );
  fireEvent.change(screen.getByRole("searchbox", { name: /Lọc catalog/i }), {
    target: { value: "không tồn tại" },
  });

  expect(screen.getByText(/Không có sản phẩm phù hợp/i)).toBeInTheDocument();
  expect(screen.queryByText("Sản phẩm tổng hợp")).not.toBeInTheDocument();
});
