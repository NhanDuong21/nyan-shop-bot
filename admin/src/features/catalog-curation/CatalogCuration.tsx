import { useId, useState } from "react";

import type { Money } from "../../api";
import type {
  CatalogCurationListing,
  CatalogCurationListingPatch,
  CatalogCurationOffer,
  CatalogCurationProps,
} from "../../catalog-curation-state";

import "./catalog-curation.css";

const integerFormatter = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
});

function formatMinorMoney(money: Money | null | undefined): string {
  if (!money) {
    return "Chưa đặt giá";
  }
  return `${integerFormatter.format(money.amount_minor)} ${money.currency}`;
}

function supplierDisplayName(supplier: string): string {
  if (supplier === "khommo") return "KhoMMO";
  if (supplier === "vietshare") return "VietShare";
  return supplier;
}

export function CatalogCuration({
  state,
  onRetry,
  onCreateListing,
  onAssignOffer,
  onUpdateListing,
  onMoveListing,
  onDeleteListing,
  onSave,
  onReset,
}: CatalogCurationProps) {
  const [filterQuery, setFilterQuery] = useState("");
  const searchInputId = useId();

  if (state.kind === "loading") {
    return (
      <main className="catalog-curation" id="catalog-content">
        <div className="curation-state-panel" role="status">
          <strong>Đang tải không gian quản trị catalog…</strong>
          <span>Đang đồng bộ danh mục nguồn và cấu hình Nyan Shop.</span>
        </div>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="catalog-curation" id="catalog-content">
        <section className="curation-state-panel curation-state-panel-error" role="alert">
          <strong>Không đọc được danh mục quản trị</strong>
          <span>{state.message}</span>
          <button type="button" className="curation-btn curation-btn-primary" onClick={onRetry}>
            Thử lại
          </button>
        </section>
      </main>
    );
  }

  if (state.kind === "empty") {
    return (
      <main className="catalog-curation" id="catalog-content">
        <div className="curation-state-panel" role="status">
          <strong>Chưa có sản phẩm nguồn nào để cấu hình.</strong>
          <span>Không tìm thấy đề nghị nào từ các nguồn supplier để biên tập catalog.</span>
        </div>
      </main>
    );
  }

  const { offers, listings, save, sourcePartial, unresolvedOfferCount } = state;
  const isSaving = save.kind === "saving";
  const isDirty = save.kind === "dirty";
  const isConflict = save.kind === "conflict";
  const isSaveError = save.kind === "error";

  const offersByKey = new Map<string, CatalogCurationOffer>(
    offers.map((offer) => [offer.key, offer]),
  );

  const unassignedOffers = offers.filter((o) => o.assignedListingId === null);

  const sortedListings = [...listings].sort((a, b) => a.sortOrder - b.sortOrder);

  const query = filterQuery.trim().toLocaleLowerCase("vi-VN");
  const filteredCandidates = unassignedOffers.filter((o) => {
    if (!query) return true;
    return (
      o.name.toLocaleLowerCase("vi-VN").includes(query) ||
      o.description.toLocaleLowerCase("vi-VN").includes(query) ||
      o.supplier.toLocaleLowerCase("vi-VN").includes(query) ||
      o.supplierProductId.toLocaleLowerCase("vi-VN").includes(query)
    );
  });

  return (
    <main className="catalog-curation" id="catalog-content">
      {/* Workspace Header */}
      <header className="curation-header">
        <div className="curation-header-title">
          <h1>Biên tập catalog Nyan Shop</h1>
          <p>
            Không gian quản trị nội bộ: chọn sản phẩm nguồn để tạo hoặc gán vào danh mục Nyan Shop.
            Giá bán lẻ được đặt theo VNĐ và hiển thị cho khách hàng mà không để lộ thông tin nguồn.
          </p>
        </div>

        {/* Global Action Toolbar */}
        <div className="curation-toolbar" role="region" aria-label="Thao tác lưu trữ">
          <div className="curation-save-status" aria-live="polite">
            {save.kind === "clean" && (
              <span className="curation-badge curation-badge-clean">Đã đồng bộ</span>
            )}
            {save.kind === "dirty" && (
              <span className="curation-badge curation-badge-dirty">Có thay đổi chưa lưu</span>
            )}
            {save.kind === "saving" && (
              <span className="curation-badge curation-badge-saving">Đang lưu thay đổi…</span>
            )}
            {save.kind === "saved" && (
              <span className="curation-badge curation-badge-saved">Đã lưu thành công</span>
            )}
            {save.kind === "conflict" && (
              <span className="curation-badge curation-badge-conflict">Xung đột phiên bản</span>
            )}
            {save.kind === "error" && (
              <span className="curation-badge curation-badge-error">Lỗi khi lưu</span>
            )}
          </div>

          <div className="curation-actions">
            <button
              type="button"
              className="curation-btn curation-btn-secondary"
              onClick={onReset}
              disabled={isSaving || (!isDirty && !isConflict && !isSaveError)}
              aria-label="Hủy các thay đổi chưa lưu và khôi phục"
            >
              Hoàn tác
            </button>
            <button
              type="button"
              className="curation-btn curation-btn-primary"
              onClick={onSave}
              disabled={isSaving || (!isDirty && !isSaveError)}
              aria-busy={isSaving}
              aria-label={isSaveError ? "Thử lưu lại thay đổi biên tập" : "Lưu các thay đổi biên tập catalog"}
            >
              {isSaving ? "Đang lưu…" : isSaveError ? "Thử lưu lại" : "Lưu thay đổi"}
            </button>
          </div>
        </div>
      </header>

      {/* Incomplete supplier evidence warning banner */}
      {(sourcePartial || unresolvedOfferCount > 0) && (
        <section
          className="curation-state-panel curation-state-panel-warning"
          role="status"
          aria-label="Cảnh báo nguồn cung chưa đầy đủ"
        >
          <strong>Dữ liệu nguồn cung chưa đầy đủ</strong>
          <span>
            {sourcePartial && unresolvedOfferCount > 0
              ? `Một số nguồn supplier chỉ phản hồi một phần và có ${unresolvedOfferCount} đề nghị chưa được đối soát. Bạn đang xem dữ liệu bằng chứng chưa hoàn chỉnh; không được tự suy đoán hoặc gán liên kết cho các sản phẩm bị thiếu.`
              : sourcePartial
                ? "Dữ liệu catalog nguồn chỉ tải được một phần từ nhà cung cấp. Bạn đang xem bằng chứng chưa hoàn chỉnh; không được tự suy đoán hoặc gán liên kết cho các sản phẩm bị thiếu."
                : `Có ${unresolvedOfferCount} đề nghị từ nguồn chưa được đối soát. Bạn đang xem dữ liệu bằng chứng chưa hoàn chỉnh; không được tự suy đoán hoặc gán liên kết cho các sản phẩm bị thiếu.`}
          </span>
        </section>
      )}

      {/* Save conflict or error alert banner */}
      {isConflict && (
        <div className="curation-state-panel curation-state-panel-warning" role="alert">
          <strong>Xung đột dữ liệu biên tập</strong>
          <span>{save.message}</span>
          <p className="curation-alert-hint">
            Dữ liệu catalog đã được thay đổi ở một phiên làm việc khác. Hãy nhấn "Hoàn tác" để nạp
            lại phiên bản mới nhất trước khi chỉnh sửa tiếp.
          </p>
        </div>
      )}
      {isSaveError && (
        <div className="curation-state-panel curation-state-panel-error" role="alert">
          <strong>Không thể lưu thay đổi</strong>
          <span>{save.message}</span>
        </div>
      )}

      {/* Two-Column Desktop Workspace */}
      <div className="curation-workspace-grid">
        {/* Left Column: Candidate Supplier Offers */}
        <section
          className="curation-section curation-offers-section"
          aria-labelledby="candidate-offers-title"
        >
          <div className="curation-section-header">
            <div>
              <h2 id="candidate-offers-title">Sản phẩm nguồn chờ biên tập</h2>
              <span className="curation-section-subtitle">
                {unassignedOffers.length} sản phẩm chưa gán · chỉ đọc từ nguồn cung
              </span>
            </div>
          </div>

          {/* Search/filter tools */}
          <div className="curation-search-box">
            <label htmlFor={searchInputId}>Lọc sản phẩm nguồn</label>
            <input
              id={searchInputId}
              type="search"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              placeholder="Tìm theo tên, mã hoặc nguồn..."
              disabled={isSaving}
            />
          </div>

          {unassignedOffers.length === 0 ? (
            <div className="curation-empty-box" role="status">
              {sourcePartial || unresolvedOfferCount > 0 ? (
                <>
                  <strong>Không có sản phẩm nguồn khả dụng</strong>
                  <p>
                    Hiện không có đề nghị nào từ nguồn cung khả dụng để biên tập và chưa thể xác nhận
                    tính đầy đủ của dữ liệu nguồn.
                  </p>
                </>
              ) : (
                <>
                  <strong>Tất cả sản phẩm nguồn đã được biên tập</strong>
                  <p>Mọi đề nghị từ supplier đều đã được tạo hoặc gán vào danh mục Nyan Shop.</p>
                </>
              )}
            </div>
          ) : filteredCandidates.length === 0 ? (
            <div className="curation-empty-box" role="status">
              <strong>Không tìm thấy sản phẩm nguồn phù hợp</strong>
              <p>Thử tìm kiếm với từ khóa khác.</p>
            </div>
          ) : (
            <div className="curation-offers-list" role="list" aria-label="Danh sách sản phẩm nguồn">
              {filteredCandidates.map((offer) => {
                return (
                  <article
                    key={offer.key}
                    role="listitem"
                    className="curation-offer-card"
                    aria-label={`Sản phẩm nguồn ${offer.name}`}
                  >
                    <div className="curation-offer-meta">
                      <span className="curation-provenance-tag">
                        {supplierDisplayName(offer.supplier)} · Mã: {offer.supplierProductId}
                      </span>
                      <span className="curation-readonly-pill">Chỉ đọc</span>
                    </div>

                    <div className="curation-offer-body">
                      <h3 className="curation-offer-title">{offer.name}</h3>
                      <p className="curation-offer-desc">{offer.description}</p>
                    </div>

                    <div className="curation-offer-finance">
                      <div className="curation-data-group">
                        <span className="curation-data-label">Giá gốc nguồn</span>
                        <strong className="curation-data-value">
                          {formatMinorMoney(offer.price)}
                        </strong>
                      </div>
                      <div className="curation-data-group">
                        <span className="curation-data-label">Tồn kho nguồn</span>
                        <span
                          className={`curation-stock-pill ${
                            offer.availableQuantity > 0
                              ? "curation-stock-available"
                              : "curation-stock-empty"
                          }`}
                        >
                          {offer.availableQuantity > 0
                            ? `${offer.availableQuantity} có sẵn`
                            : "Hết hàng"}
                        </span>
                      </div>
                    </div>

                    <div className="curation-offer-actions">
                      <button
                        type="button"
                        className="curation-btn curation-btn-accent"
                        onClick={() => onCreateListing(offer.key)}
                        disabled={isSaving}
                        aria-label={`Tạo sản phẩm Nyan mới từ ${offer.name}`}
                      >
                        Tạo mục Nyan mới
                      </button>

                      {listings.length > 0 && (
                        <div className="curation-assign-inline">
                          <label
                            htmlFor={`assign-select-${offer.key}`}
                            className="sr-only"
                          >
                            Gán {offer.name} vào danh mục Nyan
                          </label>
                          <select
                            id={`assign-select-${offer.key}`}
                            disabled={isSaving}
                            defaultValue=""
                            onChange={(e) => {
                              const val = e.target.value;
                              if (val) {
                                onAssignOffer(offer.key, val);
                                e.target.value = "";
                              }
                            }}
                          >
                            <option value="" disabled>
                              Gán vào mục Nyan…
                            </option>
                            {sortedListings.map((l) => (
                              <option key={l.id} value={l.id}>
                                {l.name || "Mục chưa đặt tên"} (ID: {l.id.slice(0, 8)})
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        {/* Right Column: Canonical Nyan Listings */}
        <section
          className="curation-section curation-listings-section"
          aria-labelledby="canonical-listings-title"
        >
          <div className="curation-section-header">
            <div>
              <h2 id="canonical-listings-title">Danh mục sản phẩm Nyan Shop</h2>
              <span className="curation-section-subtitle">
                {listings.length} mục hàng · có thể chỉnh sửa hiển thị, giá bán lẻ và thứ tự
              </span>
            </div>
          </div>

          {listings.length === 0 ? (
            <div className="curation-empty-box" role="status">
              <strong>Chưa có mục hàng Nyan nào</strong>
              <p>
                Chọn một sản phẩm từ cột "Sản phẩm nguồn chờ biên tập" và nhấn "Tạo mục Nyan mới"
                để bắt đầu danh mục.
              </p>
            </div>
          ) : (
            <div className="curation-listings-list" role="list" aria-label="Danh sách mục Nyan Shop">
              {sortedListings.map((listing, index) => {
                const assignedOffersForListing = listing.offerKeys
                  .map((k) => offersByKey.get(k))
                  .filter((o): o is CatalogCurationOffer => o !== undefined);

                return (
                  <ListingEditorItem
                    key={listing.id}
                    listing={listing}
                    assignedOffers={assignedOffersForListing}
                    index={index}
                    totalCount={sortedListings.length}
                    isSaving={isSaving}
                    onUpdateListing={onUpdateListing}
                    onMoveListing={onMoveListing}
                    onDeleteListing={onDeleteListing}
                    onAssignOffer={onAssignOffer}
                  />
                );
              })}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

interface ListingEditorItemProps {
  listing: CatalogCurationListing;
  assignedOffers: CatalogCurationOffer[];
  index: number;
  totalCount: number;
  isSaving: boolean;
  onUpdateListing: (listingId: string, patch: CatalogCurationListingPatch) => void;
  onMoveListing: (listingId: string, direction: "up" | "down") => void;
  onDeleteListing: (listingId: string) => void;
  onAssignOffer: (offerKey: string, listingId: string | null) => void;
}

function ListingEditorItem({
  listing,
  assignedOffers,
  index,
  totalCount,
  isSaving,
  onUpdateListing,
  onMoveListing,
  onDeleteListing,
  onAssignOffer,
}: ListingEditorItemProps) {
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const priceInputId = useId();
  const nameInputId = useId();
  const descInputId = useId();
  const catInputId = useId();
  const visInputId = useId();

  const handlePriceChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawVal = e.target.value.trim();
    if (rawVal === "") {
      onUpdateListing(listing.id, { retailPrice: null });
      return;
    }
    const num = Number(rawVal);
    if (Number.isSafeInteger(num) && num >= 0) {
      onUpdateListing(listing.id, {
        retailPrice: {
          amount_minor: num,
          currency: "VND",
          unit: "minor",
        },
      });
    }
  };

  return (
    <article
      role="listitem"
      className="curation-listing-card"
      aria-label={`Mục hàng Nyan ${listing.name || "Chưa đặt tên"}`}
    >
      {/* Listing card top bar: order controls, visibility, ID */}
      <div className="curation-listing-card-header">
        <div className="curation-order-controls">
          <span className="curation-order-number" aria-label={`Thứ tự ${listing.sortOrder}`}>
            #{listing.sortOrder}
          </span>
          <button
            type="button"
            className="curation-btn-icon"
            onClick={() => onMoveListing(listing.id, "up")}
            disabled={isSaving || index === 0}
            aria-label={`Di chuyển "${listing.name || "mục này"}" lên trên`}
            title="Lên trên"
          >
            ↑
          </button>
          <button
            type="button"
            className="curation-btn-icon"
            onClick={() => onMoveListing(listing.id, "down")}
            disabled={isSaving || index === totalCount - 1}
            aria-label={`Di chuyển "${listing.name || "mục này"}" xuống dưới`}
            title="Xuống dưới"
          >
            ↓
          </button>
        </div>

        <div className="curation-listing-header-meta">
          <label className="curation-toggle-label" htmlFor={visInputId}>
            <input
              id={visInputId}
              type="checkbox"
              checked={listing.visible}
              disabled={isSaving}
              onChange={(e) => onUpdateListing(listing.id, { visible: e.target.checked })}
            />
            <span>{listing.visible ? "Đang hiển thị" : "Đang ẩn"}</span>
          </label>
          <button
            type="button"
            className="curation-btn-delete"
            onClick={() => onDeleteListing(listing.id)}
            disabled={isSaving}
            aria-label={`Xóa mục hàng "${listing.name || "Chưa đặt tên"}"`}
            title="Xóa mục hàng khỏi bản nháp"
          >
            Xóa mục
          </button>
        </div>
      </div>

      {/* Edit fields form */}
      <div className="curation-form-grid">
        <div className="curation-form-group curation-col-full">
          <label htmlFor={nameInputId}>Tên sản phẩm hiển thị với khách</label>
          <input
            id={nameInputId}
            type="text"
            value={listing.name}
            disabled={isSaving}
            onChange={(e) => onUpdateListing(listing.id, { name: e.target.value })}
            placeholder="Ví dụ: Tài khoản Netflix Premium 1 tháng"
          />
        </div>

        <div className="curation-form-group curation-col-full">
          <label htmlFor={descInputId}>Mô tả sản phẩm cho khách</label>
          <textarea
            id={descInputId}
            rows={2}
            value={listing.description}
            disabled={isSaving}
            onChange={(e) => onUpdateListing(listing.id, { description: e.target.value })}
            placeholder="Mô tả thông tin quyền lợi, bảo hành cho khách…"
          />
        </div>

        <div className="curation-form-group">
          <label htmlFor={catInputId}>Danh mục (tùy chọn)</label>
          <input
            id={catInputId}
            type="text"
            value={listing.category ?? ""}
            disabled={isSaving}
            onChange={(e) =>
              onUpdateListing(listing.id, {
                category: e.target.value.trim() === "" ? null : e.target.value,
              })
            }
            placeholder="Ví dụ: Giải trí, Học tập…"
          />
        </div>

        <div className="curation-form-group">
          <label htmlFor={priceInputId}>Giá bán lẻ Nyan (VNĐ nguyên)</label>
          <input
            id={priceInputId}
            type="number"
            min="0"
            step="1"
            value={listing.retailPrice ? listing.retailPrice.amount_minor : ""}
            disabled={isSaving}
            onChange={handlePriceChange}
            placeholder="Nhập giá VNĐ..."
          />
          <span className="curation-field-hint">
            Định dạng: {formatMinorMoney(listing.retailPrice)}
          </span>
        </div>
      </div>

      {/* Linked Supplier Offers Provenance Area (Admin only) */}
      <div className="curation-linked-offers-area">
        <div className="curation-linked-header">
          <span className="curation-linked-title">
            Nguồn cung đã liên kết ({assignedOffers.length})
          </span>
          <span className="curation-provenance-note">Chỉ hiển thị cho quản trị viên</span>
        </div>

        {assignedOffers.length === 0 ? (
          <div className="curation-linked-empty">
            <span>Mục này chưa có nguồn cung liên kết nào. Khách hàng sẽ không thể mua được.</span>
          </div>
        ) : (
          <ul className="curation-linked-offers-list" aria-label="Nguồn cung đã liên kết">
            {assignedOffers.map((offer) => (
              <li key={offer.key} className="curation-linked-offer-row">
                <div className="curation-linked-offer-info">
                  <strong>{offer.name}</strong>
                  <span className="curation-linked-offer-meta">
                    {supplierDisplayName(offer.supplier)} · ID: {offer.supplierProductId} · Giá gốc:{" "}
                    {formatMinorMoney(offer.price)} · Tồn kho: {offer.availableQuantity}
                  </span>
                </div>
                <button
                  type="button"
                  className="curation-btn-unlink"
                  onClick={() => onAssignOffer(offer.key, null)}
                  disabled={isSaving}
                  aria-label={`Gỡ nguồn ${offer.name} khỏi mục này`}
                >
                  Gỡ nguồn
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Compact Customer Preview Drawer / Box */}
      <div className="curation-customer-preview-box">
        <div className="curation-preview-toggle-bar">
          <button
            type="button"
            className="curation-preview-toggle-btn"
            onClick={() => setIsPreviewOpen((prev) => !prev)}
            aria-expanded={isPreviewOpen}
            aria-controls={`preview-panel-${listing.id}`}
          >
            <span>Xem trước giao diện khách hàng</span>
            <span className="curation-preview-arrow" aria-hidden="true">
              {isPreviewOpen ? "Thu gọn" : "Mở xem"}
            </span>
          </button>
        </div>

        {isPreviewOpen && (
          <div
            id={`preview-panel-${listing.id}`}
            className="curation-customer-preview-content"
            aria-label="Xem trước hiển thị phía khách hàng"
          >
            <div className="curation-preview-badge-row">
              <span className="curation-preview-shop-tag">Nyan Shop</span>
              {listing.category && (
                <span className="curation-preview-category-tag">{listing.category}</span>
              )}
              <span
                className={`curation-preview-status-tag ${
                  listing.visible
                    ? "curation-preview-status-visible"
                    : "curation-preview-status-hidden"
                }`}
              >
                {listing.visible ? "Đang hiển thị" : "Đang ẩn"}
              </span>
            </div>

            <h4 className="curation-preview-product-name">
              {listing.name.trim() || "(Chưa có tiêu đề sản phẩm)"}
            </h4>

            <p className="curation-preview-product-desc">
              {listing.description.trim() || "(Chưa có nội dung mô tả cho khách hàng)"}
            </p>

            <div className="curation-preview-price-row">
              <span className="curation-preview-price-label">Giá niêm yết:</span>
              <strong className="curation-preview-price-value">
                {formatMinorMoney(listing.retailPrice)}
              </strong>
            </div>

            <div className="curation-preview-safety-footer">
              <small>
                Xem trước chỉ mang tính chất hiển thị: Không hiển thị thông tin nhà cung ứng,
                mã nguồn, giá gốc hay tồn kho cho khách hàng. Không thực hiện mua bán trên giao diện này.
              </small>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
