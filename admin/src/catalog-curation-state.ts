import type { CatalogSupplier, Money } from "./api";

export type LiveCatalogSupplier = Exclude<CatalogSupplier, "mock">;

export interface CatalogCurationOffer {
  key: string;
  supplier: LiveCatalogSupplier;
  supplierProductId: string;
  name: string;
  description: string;
  price: Money;
  availableQuantity: number;
  assignedListingId: string | null;
  readOnly: true;
}

export interface CatalogCurationListing {
  id: string;
  name: string;
  description: string;
  category: string | null;
  visible: boolean;
  sortOrder: number;
  retailPrice: Money | null;
  offerKeys: string[];
}

export type CatalogCurationListingPatch = Partial<
  Pick<
    CatalogCurationListing,
    "name" | "description" | "category" | "visible" | "retailPrice"
  >
>;

export type CatalogCurationSaveState =
  | { kind: "clean" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string }
  | { kind: "conflict"; message: string };

export type CatalogCurationState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "empty" }
  | {
      kind: "ready";
      revision: number;
      offers: CatalogCurationOffer[];
      listings: CatalogCurationListing[];
      save: CatalogCurationSaveState;
    };

export interface CatalogCurationProps {
  state: CatalogCurationState;
  onRetry: () => void;
  onCreateListing: (offerKey: string) => void;
  onAssignOffer: (offerKey: string, listingId: string | null) => void;
  onUpdateListing: (listingId: string, patch: CatalogCurationListingPatch) => void;
  onMoveListing: (listingId: string, direction: "up" | "down") => void;
  onSave: () => void;
  onReset: () => void;
}
