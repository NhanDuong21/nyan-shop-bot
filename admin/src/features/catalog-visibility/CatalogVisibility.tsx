import type { CatalogVisibilityProps } from "../../catalog-state";

import "./catalog-visibility.css";

const moneyFormatter = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

export function CatalogVisibility({ state, onRetry }: CatalogVisibilityProps) {
  return (
    <main className="catalog-visibility">
      <header className="hero">
        <div>
          <p className="eyebrow">NYAN SHOP BOT · FOUNDATION</p>
          <h1>Danh mục quản trị</h1>
          <p className="lede">
            Bản local chỉ đọc catalog tổng hợp từ backend. Không có thao tác mua hàng hay thanh toán.
          </p>
        </div>
        <span className="mode-badge" aria-label="Môi trường mock">
          MOCK
        </span>
      </header>

      <aside className="warning" role="note">
        Admin chưa có xác thực hoàn chỉnh và chỉ được bind vào localhost trong Phase 0.
      </aside>

      <section aria-live="polite" aria-busy={state.kind === "loading"}>
        {state.kind === "loading" && <p className="status">Đang tải catalog mock…</p>}
        {state.kind === "error" && (
          <div className="status error" role="alert">
            <p>Không đọc được backend: {state.message}</p>
            <button type="button" onClick={onRetry}>
              Thử lại
            </button>
          </div>
        )}
        {state.kind === "empty" && <p className="status">Catalog mock đang trống.</p>}
        {state.kind === "success" && (
          <div className="catalog-grid">
            {state.items.map((item) => (
              <article className="product-card" key={item.id} tabIndex={0}>
                <div className="card-meta">
                  <span>MOCK</span>
                  <span
                    className={`card-stock ${
                      item.available_quantity <= 0 ? "out-of-stock" : ""
                    }`}
                  >
                    {item.available_quantity > 0
                      ? `${item.available_quantity} mẫu`
                      : "Hết mẫu"}
                  </span>
                </div>
                <h2>{item.name}</h2>
                <p>{item.description}</p>
                <strong>{moneyFormatter.format(item.price.amount_minor)}</strong>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
