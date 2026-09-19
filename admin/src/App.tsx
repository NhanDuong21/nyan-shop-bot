import { useEffect, useState } from "react";

import { type CatalogItem, fetchCatalog } from "./api";

type CatalogState =
  | { kind: "loading" }
  | { kind: "ready"; items: CatalogItem[] }
  | { kind: "error"; message: string };

const moneyFormatter = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

export function App() {
  const [catalog, setCatalog] = useState<CatalogState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    void fetchCatalog(controller.signal)
      .then((result) => setCatalog({ kind: "ready", items: result.items }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : "Lỗi không xác định";
          setCatalog({ kind: "error", message });
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <main>
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

      <section aria-live="polite" aria-busy={catalog.kind === "loading"}>
        {catalog.kind === "loading" && <p className="status">Đang tải catalog mock…</p>}
        {catalog.kind === "error" && (
          <p className="status error">Không đọc được backend: {catalog.message}</p>
        )}
        {catalog.kind === "ready" && catalog.items.length === 0 && (
          <p className="status">Catalog mock đang trống.</p>
        )}
        {catalog.kind === "ready" && catalog.items.length > 0 && (
          <div className="catalog-grid">
            {catalog.items.map((item) => (
              <article className="product-card" key={item.id}>
                <div className="card-meta">
                  <span>MOCK</span>
                  <span>{item.available_quantity > 0 ? `${item.available_quantity} mẫu` : "Hết mẫu"}</span>
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
