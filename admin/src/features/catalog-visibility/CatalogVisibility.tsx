import { useState } from "react";

import type { CatalogVisibilityProps } from "../../catalog-state";

import "./catalog-visibility.css";

const moneyFormatter = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

export function CatalogVisibility({ state, onRetry }: CatalogVisibilityProps) {
  const [filterQuery, setFilterQuery] = useState("");
  const normalizedQuery = filterQuery.trim().toLocaleLowerCase("vi-VN");
  const visibleItems =
    state.kind === "success"
      ? state.items.filter((item) =>
          [item.name, item.description, item.supplier].some((value) =>
            value.toLocaleLowerCase("vi-VN").includes(normalizedQuery),
          ),
        )
      : [];

  return (
    <main className="catalog-visibility" id="catalog-content">
      <header className="catalog-heading">
        <div>
          <h1>Danh mục</h1>
          <p>
            Dữ liệu tổng hợp từ backend mock. Giá hiển thị để kiểm thử và không tạo giao dịch.
          </p>
        </div>
        {state.kind === "success" && (
          <span className="catalog-count">
            {normalizedQuery
              ? `${visibleItems.length}/${state.items.length} sản phẩm`
              : `${state.items.length} sản phẩm`}
          </span>
        )}
      </header>

      <section className="catalog-state" aria-live="polite" aria-busy={state.kind === "loading"}>
        {state.kind === "loading" && (
          <div className="state-panel" role="status">
            <strong>Đang tải catalog mock…</strong>
            <span>Backend đang chuẩn bị dữ liệu tổng hợp.</span>
          </div>
        )}
        {state.kind === "error" && (
          <div className="state-panel state-panel-error" role="alert">
            <strong>Không đọc được backend</strong>
            <span>{state.message}</span>
            <button type="button" onClick={onRetry}>
              Thử lại
            </button>
          </div>
        )}
        {state.kind === "empty" && (
          <div className="state-panel" role="status">
            <strong>Catalog mock đang trống.</strong>
            <span>Chưa có sản phẩm tổng hợp nào để hiển thị.</span>
          </div>
        )}
        {state.kind === "success" && (
          <div className="catalog-success">
            <div className="catalog-tools">
              <label htmlFor="catalog-filter">Lọc catalog</label>
              <input
                id="catalog-filter"
                type="search"
                value={filterQuery}
                placeholder="Tên sản phẩm hoặc supplier"
                onChange={(event) => setFilterQuery(event.target.value)}
              />
            </div>

            {visibleItems.length === 0 ? (
              <div className="state-panel" role="status">
                <strong>Không có sản phẩm phù hợp.</strong>
                <span>Thử tên sản phẩm hoặc supplier khác.</span>
              </div>
            ) : (
              <div className="catalog-table-region" tabIndex={0} aria-label="Bảng danh mục mock">
                <table className="catalog-table">
                  <thead>
                    <tr>
                      <th scope="col">Sản phẩm</th>
                      <th scope="col">Supplier</th>
                      <th scope="col">Tồn kho</th>
                      <th scope="col">Giá mock</th>
                      <th scope="col">Trạng thái</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((item) => (
                      <tr key={item.id}>
                        <th scope="row" data-label="Sản phẩm">
                          <strong>{item.name}</strong>
                          <span>{item.description}</span>
                        </th>
                        <td data-label="Supplier">{item.supplier}</td>
                        <td data-label="Tồn kho">{item.available_quantity}</td>
                        <td data-label="Giá mock">
                          {moneyFormatter.format(item.price.amount_minor)}
                        </td>
                        <td data-label="Trạng thái">
                          <span
                            className={
                              item.available_quantity > 0
                                ? "availability availability-ready"
                                : "availability availability-empty"
                            }
                          >
                            {item.available_quantity > 0 ? "Có sẵn" : "Hết mẫu"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
