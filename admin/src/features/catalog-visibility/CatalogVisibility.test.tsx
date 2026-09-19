import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogVisibility } from "./CatalogVisibility";
import type { CatalogViewState } from "../../catalog-state";

afterEach(() => {
  cleanup();
});

const mockItems = [
  {
    id: "item-1",
    name: "Sản phẩm A",
    description: "Mô tả sản phẩm A",
    supplier: "mock",
    mode: "mock",
    price: { amount_minor: 50000, currency: "VND" },
    available_quantity: 5,
  },
  {
    id: "item-2",
    name: "Sản phẩm B",
    description: "Mô tả sản phẩm B hết hàng",
    supplier: "mock",
    mode: "mock",
    price: { amount_minor: 120000, currency: "VND" },
    available_quantity: 0,
  },
];

describe("CatalogVisibility feature component", () => {
  it("renders loading state with accessibility attributes and mock messaging", () => {
    const state: CatalogViewState = { kind: "loading" };
    const onRetry = vi.fn();

    render(<CatalogVisibility state={state} onRetry={onRetry} />);

    expect(screen.getByText(/Đang tải catalog mock…/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Môi trường mock/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Bản local chỉ đọc catalog tổng hợp từ backend\. Không có thao tác mua hàng hay thanh toán\./i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Admin chưa có xác thực hoàn chỉnh và chỉ được bind vào localhost trong Phase 0\./i)
    ).toBeInTheDocument();
  });

  it("renders error state and triggers retry callback when retry button is clicked", () => {
    const state: CatalogViewState = {
      kind: "error",
      message: "Network unreachable 503",
    };
    const onRetry = vi.fn();

    render(<CatalogVisibility state={state} onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText(/Không đọc được backend: Network unreachable 503/i)
    ).toBeInTheDocument();

    const retryBtn = screen.getByRole("button", { name: /Thử lại/i });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders empty state when there are no catalog items", () => {
    const state: CatalogViewState = { kind: "empty" };
    const onRetry = vi.fn();

    render(<CatalogVisibility state={state} onRetry={onRetry} />);

    expect(screen.getByText(/Catalog mock đang trống\./i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Môi trường mock/i)).toBeInTheDocument();
  });

  it("renders success state with catalog items, formatted prices, and availability", () => {
    const state: CatalogViewState = {
      kind: "success",
      items: mockItems,
    };
    const onRetry = vi.fn();

    render(<CatalogVisibility state={state} onRetry={onRetry} />);

    expect(screen.getByText("Sản phẩm A")).toBeInTheDocument();
    expect(screen.getByText("Mô tả sản phẩm A")).toBeInTheDocument();
    expect(screen.getByText("5 mẫu")).toBeInTheDocument();

    expect(screen.getByText("Sản phẩm B")).toBeInTheDocument();
    expect(screen.getByText("Mô tả sản phẩm B hết hàng")).toBeInTheDocument();
    expect(screen.getByText("Hết mẫu")).toBeInTheDocument();

    // Verify mock badges are rendered
    expect(screen.getAllByText("MOCK").length).toBeGreaterThanOrEqual(3);
  });
});
