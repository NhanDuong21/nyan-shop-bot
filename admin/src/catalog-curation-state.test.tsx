import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { useCatalogCurationState } from "./catalog-curation-state";

const firstOfferKey = ["khommo", "fixture", "one"].join(":");
const secondOfferKey = ["vietshare", "fixture", "two"].join(":");

const offer = {
  key: firstOfferKey,
  supplier: "khommo" as const,
  supplier_product_id: "source-1",
  name: "Sản phẩm nguồn",
  description: "Mô tả chỉ đọc từ nguồn.",
  price: { amount_minor: 20_000, currency: "VND", unit: "minor" as const },
  available_quantity: 5,
  assigned_listing_id: null,
  read_only: true as const,
};

const secondOffer = {
  ...offer,
  key: secondOfferKey,
  supplier: "vietshare" as const,
  supplier_product_id: "source-2",
  name: "Nguồn thay thế",
};

function workspace(revision = 0, listings: unknown[] = []) {
  return {
    revision,
    offers: [offer, secondOffer],
    listings,
    unresolved_offer_count: 0,
    source_partial: false,
    read_only: true,
    supplier_writes_enabled: false,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("loads offers and keeps grouping entirely owner-authored", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(workspace()))));
  const { result } = renderHook(() => useCatalogCurationState(true));

  await waitFor(() => expect(result.current.state.kind).toBe("ready"));
  act(() => result.current.onCreateListing(offer.key));

  expect(result.current.state.kind).toBe("ready");
  if (result.current.state.kind !== "ready") throw new Error("expected ready state");
  expect(result.current.state.listings).toHaveLength(1);
  expect(result.current.state.sourcePartial).toBe(false);
  expect(result.current.state.unresolvedOfferCount).toBe(0);
  const listingId = result.current.state.listings[0].id;
  expect(result.current.state.listings[0].offerKeys).toEqual([offer.key]);
  expect(result.current.state.offers[1].assignedListingId).toBeNull();

  act(() => result.current.onAssignOffer(secondOffer.key, listingId));
  if (result.current.state.kind !== "ready") throw new Error("expected ready state");
  expect(result.current.state.listings[0].offerKeys).toEqual([offer.key, secondOffer.key]);
  expect(result.current.state.offers[1].assignedListingId).toBe(listingId);
});

test("saves an integer VND draft with its exact optimistic revision", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const request = JSON.parse(String(init.body)) as { listings: unknown[] };
      return Promise.resolve(jsonResponse(workspace(1, request.listings)));
    }
    return Promise.resolve(jsonResponse(workspace()));
  });
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useCatalogCurationState(true));
  await waitFor(() => expect(result.current.state.kind).toBe("ready"));

  act(() => result.current.onCreateListing(offer.key));
  if (result.current.state.kind !== "ready") throw new Error("expected ready state");
  const listingId = result.current.state.listings[0].id;
  act(() =>
    result.current.onUpdateListing(listingId, {
      retailPrice: { amount_minor: 35_000, currency: "VND", unit: "minor" },
      visible: true,
    }),
  );
  act(() => result.current.onSave());

  await waitFor(() => {
    expect(result.current.state.kind).toBe("ready");
    if (result.current.state.kind === "ready") {
      expect(result.current.state.save.kind).toBe("saved");
      expect(result.current.state.revision).toBe(1);
    }
  });
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(put).toBeDefined();
  const request = JSON.parse(String(put?.[1]?.body)) as {
    expected_revision: number;
    listings: Array<{ retail_price: { amount_minor: number }; visible: boolean }>;
  };
  expect(request.expected_revision).toBe(0);
  expect(request.listings[0].retail_price.amount_minor).toBe(35_000);
  expect(request.listings[0].visible).toBe(true);
});

test("fails closed on removing the last offer and surfaces revision conflicts", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "PUT") {
      return Promise.resolve(jsonResponse({ detail: "stale" }, 409));
    }
    return Promise.resolve(jsonResponse(workspace()));
  });
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useCatalogCurationState(true));
  await waitFor(() => expect(result.current.state.kind).toBe("ready"));

  act(() => result.current.onCreateListing(offer.key));
  if (result.current.state.kind !== "ready") throw new Error("expected ready state");
  const listing = result.current.state.listings[0];
  act(() => result.current.onAssignOffer(offer.key, null));
  if (result.current.state.kind !== "ready") throw new Error("expected ready state");
  expect(result.current.state.listings[0].offerKeys).toEqual([offer.key]);
  expect(result.current.state.save.kind).toBe("error");

  act(() => result.current.onDeleteListing(listing.id));
  if (result.current.state.kind !== "ready") throw new Error("expected ready state");
  expect(result.current.state.listings).toEqual([]);
  expect(result.current.state.offers[0].assignedListingId).toBeNull();

  act(() => result.current.onCreateListing(offer.key));
  if (result.current.state.kind !== "ready") throw new Error("expected ready state");
  const replacement = result.current.state.listings[0];

  act(() =>
    result.current.onUpdateListing(replacement.id, {
      retailPrice: { amount_minor: 35_000, currency: "VND", unit: "minor" },
    }),
  );
  act(() => result.current.onSave());
  await waitFor(() => {
    if (result.current.state.kind !== "ready") throw new Error("expected ready state");
    expect(result.current.state.save.kind).toBe("conflict");
  });
});
