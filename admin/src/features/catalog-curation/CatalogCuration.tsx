import type { CatalogCurationProps } from "../../catalog-curation-state";

import "./catalog-curation.css";

export function CatalogCuration({ state, onRetry }: CatalogCurationProps) {
  if (state.kind === "loading") {
    return <p role="status">Đang tải không gian quản trị catalog…</p>;
  }
  if (state.kind === "error") {
    return (
      <section role="alert">
        <p>{state.message}</p>
        <button type="button" onClick={onRetry}>
          Thử lại
        </button>
      </section>
    );
  }
  if (state.kind === "empty") {
    return <p role="status">Chưa có sản phẩm nguồn nào để cấu hình.</p>;
  }
  return (
    <main className="catalog-curation" id="catalog-curation-content">
      <h1>Catalog Nyan Shop</h1>
      <p>{state.listings.length} sản phẩm Nyan đang được cấu hình.</p>
    </main>
  );
}
