import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { Money } from "../../api";
import type {
  CatalogCurationListing,
  CatalogCurationOffer,
  CatalogCurationProps,
  CatalogCurationState,
} from "../../catalog-curation-state";
import { CatalogCuration } from "./CatalogCuration";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const syntheticOffer1Price: Money = {
  amount_minor: 50000,
  currency: "VND",
  unit: "minor",
};

const syntheticOffer2Price: Money = {
  amount_minor: 40000,
  currency: "VND",
  unit: "minor",
};

const syntheticListing1Price: Money = {
  amount_minor: 65000,
  currency: "VND",
  unit: "minor",
};

const syntheticListing2Price: Money = {
  amount_minor: 45000,
  currency: "VND",
  unit: "minor",
};

const syntheticOffer1: CatalogCurationOffer = {
  key: "khommo:prod-101",
  supplier: "khommo",
  supplierProductId: "SKU-KM-01",
  name: "KhoMMO Premium Key 1M",
  description: "Bản quyền 1 tháng từ nhà cung ứng KhoMMO.",
  price: syntheticOffer1Price,
  availableQuantity: 12,
  assignedListingId: "nyan-item-1",
  readOnly: true,
};

const syntheticOffer2: CatalogCurationOffer = {
  key: "vietshare:prod-202",
  supplier: "vietshare",
  supplierProductId: "VS-ACC-88",
  name: "VietShare Family Slot",
  description: "Suất dùng gia đình ổn định nguồn VietShare.",
  price: syntheticOffer2Price,
  availableQuantity: 5,
  assignedListingId: null,
  readOnly: true,
};

const syntheticListing1: CatalogCurationListing = {
  id: "nyan-item-1",
  name: "Gói Giải Trí Nyan 1 Tháng",
  description: "Trải nghiệm mượt mà, hỗ trợ kỹ thuật nhanh.",
  category: "Giải trí",
  visible: true,
  sortOrder: 0,
  retailPrice: syntheticListing1Price,
  offerKeys: ["khommo:prod-101"],
};

const syntheticListing2: CatalogCurationListing = {
  id: "nyan-item-2",
  name: "Gói Học Tập Nyan",
  description: "Tài liệu và công cụ phục vụ học tập.",
  category: "Học tập",
  visible: false,
  sortOrder: 1,
  retailPrice: syntheticListing2Price,
  offerKeys: [],
};

function createMockProps(overrides?: Partial<CatalogCurationProps>): CatalogCurationProps {
  const defaultState: CatalogCurationState = {
    kind: "ready",
    revision: 1,
    offers: [syntheticOffer1, syntheticOffer2],
    listings: [syntheticListing1, syntheticListing2],
    sourcePartial: false,
    unresolvedOfferCount: 0,
    save: { kind: "clean" },
  };

  return {
    state: defaultState,
    onRetry: vi.fn(),
    onCreateListing: vi.fn(),
    onAssignOffer: vi.fn(),
    onUpdateListing: vi.fn(),
    onMoveListing: vi.fn(),
    onDeleteListing: vi.fn(),
    onSave: vi.fn(),
    onReset: vi.fn(),
    ...overrides,
  };
}

describe("CatalogCuration UI feature component", () => {
  test("renders loading state with skip-link id catalog-content", () => {
    const props = createMockProps({ state: { kind: "loading" } });
    render(<CatalogCuration {...props} />);

    const root = screen.getByRole("main");
    expect(root).toHaveAttribute("id", "catalog-content");
    expect(screen.getByText(/Đang tải không gian quản trị catalog/i)).toBeInTheDocument();
  });

  test("renders error state with skip-link id catalog-content and triggers onRetry", () => {
    const onRetry = vi.fn();
    const props = createMockProps({
      state: { kind: "error", message: "Mất kết nối cơ sở dữ liệu." },
      onRetry,
    });
    render(<CatalogCuration {...props} />);

    const root = screen.getByRole("main");
    expect(root).toHaveAttribute("id", "catalog-content");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Mất kết nối cơ sở dữ liệu/i)).toBeInTheDocument();

    const retryBtn = screen.getByRole("button", { name: /Thử lại/i });
    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test("renders empty state with skip-link id catalog-content", () => {
    const props = createMockProps({ state: { kind: "empty" } });
    render(<CatalogCuration {...props} />);

    const root = screen.getByRole("main");
    expect(root).toHaveAttribute("id", "catalog-content");
    expect(screen.getByText(/Chưa có sản phẩm nguồn nào để cấu hình/i)).toBeInTheDocument();
  });

  test("renders populated ready state with skip-link id and correct badges", () => {
    const props = createMockProps();
    render(<CatalogCuration {...props} />);

    const root = screen.getByRole("main");
    expect(root).toHaveAttribute("id", "catalog-content");
    expect(screen.getByText("Biên tập catalog Nyan Shop")).toBeInTheDocument();
    expect(screen.getByText("Đã đồng bộ")).toBeInTheDocument();
    expect(screen.getByText("KhoMMO Premium Key 1M")).toBeInTheDocument();

    const listing1Card = screen.getByRole("listitem", {
      name: `Mục hàng Nyan ${syntheticListing1.name}`,
    });
    expect(listing1Card).toBeInTheDocument();
    expect(
      within(listing1Card).getByLabelText(/Tên sản phẩm hiển thị với khách/i),
    ).toHaveValue(syntheticListing1.name);
  });

  test("shows accessible warning banner when sourcePartial is true and missing links must not be guessed", () => {
    const props = createMockProps({
      state: {
        kind: "ready",
        revision: 1,
        offers: [syntheticOffer1],
        listings: [syntheticListing1],
        sourcePartial: true,
        unresolvedOfferCount: 2,
        save: { kind: "clean" },
      },
    });
    render(<CatalogCuration {...props} />);

    const banner = screen.getByRole("status", { name: /Cảnh báo nguồn cung chưa đầy đủ/i });
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/không được tự suy đoán hoặc gán liên kết cho các sản phẩm bị thiếu/i);
    expect(banner).toHaveTextContent(/2 đề nghị chưa được đối soát/i);
  });

  test("handles save lifecycle states: dirty, saving, saved", () => {
    const onSave = vi.fn();
    const onReset = vi.fn();

    // Dirty state
    const { rerender } = render(
      <CatalogCuration
        {...createMockProps({
          state: {
            kind: "ready",
            revision: 1,
            offers: [syntheticOffer1],
            listings: [syntheticListing1],
            sourcePartial: false,
            unresolvedOfferCount: 0,
            save: { kind: "dirty" },
          },
          onSave,
          onReset,
        })}
      />,
    );

    expect(screen.getByText("Có thay đổi chưa lưu")).toBeInTheDocument();
    const saveBtn = screen.getByRole("button", { name: /Lưu các thay đổi biên tập catalog/i });
    const resetBtn = screen.getByRole("button", { name: /Hủy các thay đổi chưa lưu và khôi phục/i });
    expect(saveBtn).not.toBeDisabled();
    expect(resetBtn).not.toBeDisabled();

    fireEvent.click(saveBtn);
    expect(onSave).toHaveBeenCalledTimes(1);

    fireEvent.click(resetBtn);
    expect(onReset).toHaveBeenCalledTimes(1);

    // Saving state
    rerender(
      <CatalogCuration
        {...createMockProps({
          state: {
            kind: "ready",
            revision: 1,
            offers: [syntheticOffer1],
            listings: [syntheticListing1],
            sourcePartial: false,
            unresolvedOfferCount: 0,
            save: { kind: "saving" },
          },
          onSave,
          onReset,
        })}
      />,
    );

    expect(screen.getByText("Đang lưu thay đổi…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Lưu các thay đổi biên tập catalog/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Hủy các thay đổi chưa lưu và khôi phục/i })).toBeDisabled();

    // Saved state
    rerender(
      <CatalogCuration
        {...createMockProps({
          state: {
            kind: "ready",
            revision: 1,
            offers: [syntheticOffer1],
            listings: [syntheticListing1],
            sourcePartial: false,
            unresolvedOfferCount: 0,
            save: { kind: "saved" },
          },
          onSave,
          onReset,
        })}
      />,
    );

    expect(screen.getByText("Đã lưu thành công")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Lưu các thay đổi biên tập catalog/i })).toBeDisabled();
  });

  test("makes failed non-conflict save retryable without forcing an extra edit", () => {
    const onSave = vi.fn();
    const props = createMockProps({
      state: {
        kind: "ready",
        revision: 1,
        offers: [syntheticOffer1],
        listings: [syntheticListing1],
        sourcePartial: false,
        unresolvedOfferCount: 0,
        save: { kind: "error", message: "Lỗi kết nối khi ghi catalog." },
      },
      onSave,
    });
    render(<CatalogCuration {...props} />);

    expect(screen.getByText("Lỗi khi lưu")).toBeInTheDocument();
    expect(screen.getByText("Lỗi kết nối khi ghi catalog.")).toBeInTheDocument();

    const retrySaveBtn = screen.getByRole("button", { name: /Thử lưu lại thay đổi biên tập/i });
    expect(retrySaveBtn).not.toBeDisabled();
    expect(retrySaveBtn).toHaveTextContent("Thử lưu lại");

    fireEvent.click(retrySaveBtn);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  test("keeps conflict state fail-closed: save disabled, reset enabled", () => {
    const onReset = vi.fn();
    const onSave = vi.fn();
    const props = createMockProps({
      state: {
        kind: "ready",
        revision: 1,
        offers: [syntheticOffer1],
        listings: [syntheticListing1],
        sourcePartial: false,
        unresolvedOfferCount: 0,
        save: { kind: "conflict", message: "Phiên bản đã thay đổi trên máy chủ." },
      },
      onReset,
      onSave,
    });
    render(<CatalogCuration {...props} />);

    expect(screen.getByText("Xung đột phiên bản")).toBeInTheDocument();
    expect(screen.getByText("Phiên bản đã thay đổi trên máy chủ.")).toBeInTheDocument();

    const saveBtn = screen.getByRole("button", { name: /Lưu các thay đổi biên tập catalog/i });
    expect(saveBtn).toBeDisabled();

    const resetBtn = screen.getByRole("button", { name: /Hủy các thay đổi chưa lưu và khôi phục/i });
    expect(resetBtn).not.toBeDisabled();
    fireEvent.click(resetBtn);
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  test("triggers onCreateListing from unassigned candidate offer", () => {
    const onCreateListing = vi.fn();
    const props = createMockProps({ onCreateListing });
    render(<CatalogCuration {...props} />);

    const createBtn = screen.getByRole("button", {
      name: `Tạo sản phẩm Nyan mới từ ${syntheticOffer2.name}`,
    });
    fireEvent.click(createBtn);
    expect(onCreateListing).toHaveBeenCalledWith("vietshare:prod-202");
  });

  test("triggers onAssignOffer when grouping unassigned offer into existing listing", () => {
    const onAssignOffer = vi.fn();
    const props = createMockProps({ onAssignOffer });
    render(<CatalogCuration {...props} />);

    const select = screen.getByRole("combobox", {
      name: `Gán ${syntheticOffer2.name} vào danh mục Nyan`,
    });
    fireEvent.change(select, { target: { value: "nyan-item-1" } });
    expect(onAssignOffer).toHaveBeenCalledWith("vietshare:prod-202", "nyan-item-1");
  });

  test("triggers onAssignOffer to unlink offer from listing", () => {
    const onAssignOffer = vi.fn();
    const props = createMockProps({ onAssignOffer });
    render(<CatalogCuration {...props} />);

    const unlinkBtn = screen.getByRole("button", {
      name: `Gỡ nguồn ${syntheticOffer1.name} khỏi mục này`,
    });
    fireEvent.click(unlinkBtn);
    expect(onAssignOffer).toHaveBeenCalledWith("khommo:prod-101", null);
  });

  test("triggers onUpdateListing for name, description, category, and visibility", () => {
    const onUpdateListing = vi.fn();
    const props = createMockProps({ onUpdateListing });
    render(<CatalogCuration {...props} />);

    const listing1Card = screen.getByRole("listitem", {
      name: `Mục hàng Nyan ${syntheticListing1.name}`,
    });

    const nameInput = within(listing1Card).getByLabelText(/Tên sản phẩm hiển thị với khách/i);
    fireEvent.change(nameInput, { target: { value: "Gói Giải Trí Nyan Pro" } });
    expect(onUpdateListing).toHaveBeenCalledWith("nyan-item-1", { name: "Gói Giải Trí Nyan Pro" });

    const descInput = within(listing1Card).getByLabelText(/Mô tả sản phẩm cho khách/i);
    fireEvent.change(descInput, { target: { value: "Mô tả mới" } });
    expect(onUpdateListing).toHaveBeenCalledWith("nyan-item-1", { description: "Mô tả mới" });

    const catInput = within(listing1Card).getByLabelText(/Danh mục \(tùy chọn\)/i);
    fireEvent.change(catInput, { target: { value: "VIP" } });
    expect(onUpdateListing).toHaveBeenCalledWith("nyan-item-1", { category: "VIP" });

    const visCheckbox = within(listing1Card).getByRole("checkbox", { name: /Đang hiển thị/i });
    fireEvent.click(visCheckbox);
    expect(onUpdateListing).toHaveBeenCalledWith("nyan-item-1", { visible: false });
  });

  test("handles integer VND price input and rejects non-safe-integer / decimal values without truncation", () => {
    const onUpdateListing = vi.fn();
    const props = createMockProps({ onUpdateListing });
    render(<CatalogCuration {...props} />);

    const listing1Card = screen.getByRole("listitem", {
      name: `Mục hàng Nyan ${syntheticListing1.name}`,
    });
    const priceInput = within(listing1Card).getByLabelText(/Giá bán lẻ Nyan \(VNĐ nguyên\)/i);
    expect(priceInput).toHaveAttribute("step", "1");
    expect(priceInput).toHaveAttribute("min", "0");

    // Valid positive safe integer
    fireEvent.change(priceInput, { target: { value: "70000" } });
    expect(onUpdateListing).toHaveBeenCalledWith("nyan-item-1", {
      retailPrice: {
        amount_minor: 70000,
        currency: "VND",
        unit: "minor",
      },
    });

    onUpdateListing.mockClear();

    // Clearing input sets retailPrice to null
    fireEvent.change(priceInput, { target: { value: "" } });
    expect(onUpdateListing).toHaveBeenCalledWith("nyan-item-1", { retailPrice: null });

    onUpdateListing.mockClear();

    // Decimal number: must be rejected without truncation (parseInt truncation forbidden)
    fireEvent.change(priceInput, { target: { value: "70000.5" } });
    expect(onUpdateListing).not.toHaveBeenCalled();

    // Negative number: must be rejected
    fireEvent.change(priceInput, { target: { value: "-100" } });
    expect(onUpdateListing).not.toHaveBeenCalled();
  });

  test("triggers onMoveListing for reordering up and down", () => {
    const onMoveListing = vi.fn();
    const props = createMockProps({ onMoveListing });
    render(<CatalogCuration {...props} />);

    // Item 0 can only move down (up is disabled)
    const item0MoveUp = screen.getByRole("button", {
      name: `Di chuyển "${syntheticListing1.name}" lên trên`,
    });
    const item0MoveDown = screen.getByRole("button", {
      name: `Di chuyển "${syntheticListing1.name}" xuống dưới`,
    });
    expect(item0MoveUp).toBeDisabled();
    expect(item0MoveDown).not.toBeDisabled();

    fireEvent.click(item0MoveDown);
    expect(onMoveListing).toHaveBeenCalledWith("nyan-item-1", "down");

    // Item 1 can move up
    const item1MoveUp = screen.getByRole("button", {
      name: `Di chuyển "${syntheticListing2.name}" lên trên`,
    });
    fireEvent.click(item1MoveUp);
    expect(onMoveListing).toHaveBeenCalledWith("nyan-item-2", "up");
  });

  test("triggers onDeleteListing without browser dialogs", () => {
    const onDeleteListing = vi.fn();
    const props = createMockProps({ onDeleteListing });
    render(<CatalogCuration {...props} />);

    const deleteBtn = screen.getByRole("button", {
      name: `Xóa mục hàng "${syntheticListing1.name}"`,
    });
    fireEvent.click(deleteBtn);
    expect(onDeleteListing).toHaveBeenCalledWith("nyan-item-1");
  });

  test("preserves customer preview redaction: no supplier names, IDs, costs, or stock in preview", () => {
    const props = createMockProps();
    render(<CatalogCuration {...props} />);

    const listing1Card = screen.getByRole("listitem", {
      name: `Mục hàng Nyan ${syntheticListing1.name}`,
    });

    // Open customer preview for listing 1 within its card
    const previewToggleBtn = within(listing1Card).getByRole("button", {
      name: /Xem trước giao diện khách hàng/i,
    });
    fireEvent.click(previewToggleBtn);

    const previewRegion = within(listing1Card).getByLabelText("Xem trước hiển thị phía khách hàng");
    expect(previewRegion).toBeInTheDocument();

    // Display state labels check
    expect(previewRegion).toHaveTextContent("Đang hiển thị");
    expect(previewRegion).not.toHaveTextContent("Đang mở bán");

    // Scoped redaction check inside previewRegion:
    const previewText = previewRegion.textContent ?? "";
    expect(previewText.toLowerCase()).not.toContain("khommo");
    expect(previewText).not.toContain("SKU-KM-01");
    expect(previewText).not.toContain("50.000"); // supplier price
    expect(previewText).not.toContain("12 có sẵn"); // supplier stock

    // Plain text safety copy: no emojis or decorative glyphs
    const safetyFooter = previewRegion.querySelector(".curation-preview-safety-footer");
    expect(safetyFooter).toBeInTheDocument();
    expect(safetyFooter?.textContent).not.toMatch(/[✓✔★▲▼]/);
    expect(safetyFooter).toHaveTextContent(
      /Xem trước chỉ mang tính chất hiển thị: Không hiển thị thông tin nhà cung ứng/i,
    );

    // Provenance and supplier IDs remain visible only in admin linked area
    const adminProvenance = within(listing1Card).getByLabelText("Nguồn cung đã liên kết");
    expect(adminProvenance).toHaveTextContent("KhoMMO");
    expect(adminProvenance).toHaveTextContent("SKU-KM-01");
    expect(adminProvenance).toHaveTextContent("50.000 VND");
  });

  test("has no purchase, payment, top-up, or live-write money controls", () => {
    const props = createMockProps();
    render(<CatalogCuration {...props} />);

    expect(screen.queryByRole("button", { name: /mua hàng/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /thanh toán/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /nạp tiền/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /hoàn tiền/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /giao hàng/i })).not.toBeInTheDocument();
  });

  test("renders neutral fail-closed copy without all-curated claim when ready with zero offers, zero listings, and sourcePartial true", () => {
    const props = createMockProps({
      state: {
        kind: "ready",
        revision: 1,
        offers: [],
        listings: [],
        sourcePartial: true,
        unresolvedOfferCount: 0,
        save: { kind: "clean" },
      },
    });
    render(<CatalogCuration {...props} />);

    // Warning banner is visible
    const warningBanner = screen.getByRole("status", { name: /Cảnh báo nguồn cung chưa đầy đủ/i });
    expect(warningBanner).toBeInTheDocument();
    expect(warningBanner).toHaveTextContent(/Dữ liệu nguồn cung chưa đầy đủ/i);
    expect(warningBanner).toHaveTextContent(/không được tự suy đoán hoặc gán liên kết cho các sản phẩm bị thiếu/i);

    // Neutral outage / incomplete copy is visible
    expect(screen.getByText("Không có sản phẩm nguồn khả dụng")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Hiện không có đề nghị nào từ nguồn cung khả dụng để biên tập và chưa thể xác nhận tính đầy đủ của dữ liệu nguồn/i,
      ),
    ).toBeInTheDocument();

    // False "all-curated" claim must be absent
    expect(screen.queryByText("Tất cả sản phẩm nguồn đã được biên tập")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Mọi đề nghị từ supplier đều đã được tạo hoặc gán vào danh mục Nyan Shop."),
    ).not.toBeInTheDocument();

    // Listings empty state placeholder is visible
    expect(screen.getByText("Chưa có mục hàng Nyan nào")).toBeInTheDocument();

    // No write-money controls
    expect(screen.queryByRole("button", { name: /mua hàng/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /thanh toán/i })).not.toBeInTheDocument();
  });
});
