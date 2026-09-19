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

function catalogResponse(items: unknown[]) {
  return new Response(JSON.stringify({ mode: "mock", items }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const catalogItem = {
  id: "mock-item",
  name: "Sản phẩm kiểm thử",
  description: "Dữ liệu tổng hợp từ backend",
  supplier: "mock",
  mode: "mock",
  price: { amount_minor: 42000, currency: "VND" },
  available_quantity: 2,
};

test("shows the explicit loading state while the API request is pending", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

  render(<App />);

  expect(screen.getByText(/Đang tải catalog mock/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/Môi trường mock/i)).toBeInTheDocument();
});

test("renders catalog returned by the backend without replacing API data", async () => {
  const fetchMock = vi.fn().mockResolvedValue(catalogResponse([catalogItem]));
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(await screen.findByText("Sản phẩm kiểm thử")).toBeInTheDocument();
  expect(screen.getByText("Dữ liệu tổng hợp từ backend")).toBeInTheDocument();
  expect(screen.getAllByText("MOCK").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/chỉ chạy trên localhost/i)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalog",
    expect.objectContaining({ method: "GET" }),
  );
});

test("filters injected catalog data without replacing the backend source", async () => {
  const secondItem = {
    ...catalogItem,
    id: "second-item",
    name: "Mục khác",
    supplier: "fixture-supplier",
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(catalogResponse([catalogItem, secondItem])));

  render(<App />);

  expect(await screen.findByText("Sản phẩm kiểm thử")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: /Lọc catalog/i }), {
    target: { value: "fixture-supplier" },
  });

  expect(screen.queryByText("Sản phẩm kiểm thử")).not.toBeInTheDocument();
  expect(screen.getByText("Mục khác")).toBeInTheDocument();
  expect(screen.getByText("1/2 sản phẩm")).toBeInTheDocument();
});

test("shows an explicit empty state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(catalogResponse([])));

  render(<App />);

  expect(await screen.findByText(/Catalog mock đang trống/i)).toBeInTheDocument();
});

test("shows a backend error and retries through the coordinator callback", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(catalogResponse([catalogItem]));
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(await screen.findByText(/Catalog request failed with 503/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Thử lại/i }));

  expect(await screen.findByText("Sản phẩm kiểm thử")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
