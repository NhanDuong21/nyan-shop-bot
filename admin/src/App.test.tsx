import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders catalog returned by the backend and labels it mock", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        mode: "mock",
        items: [
          {
            id: "mock-item",
            name: "Sản phẩm kiểm thử",
            description: "Dữ liệu tổng hợp",
            supplier: "mock",
            mode: "mock",
            price: { amount_minor: 42000, currency: "VND" },
            available_quantity: 2,
          },
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(await screen.findByText("Sản phẩm kiểm thử")).toBeInTheDocument();
  expect(screen.getAllByText("MOCK").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/chỉ được bind vào localhost/i)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/catalog",
    expect.objectContaining({ method: "GET" }),
  );
});

test("shows a useful backend error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

  render(<App />);

  expect(await screen.findByText(/Catalog request failed with 503/i)).toBeInTheDocument();
});
