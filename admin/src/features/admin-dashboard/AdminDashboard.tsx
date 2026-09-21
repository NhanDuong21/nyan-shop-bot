import { useState } from "react";

import type { Money } from "../../api";
import type { AdminDashboardProps } from "../../catalog-state";

import "./admin-dashboard.css";

const integerFormatter = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
});

function formatMinorMoney(money: Money): string {
  return `${integerFormatter.format(money.amount_minor)} ${money.currency} · ${money.unit}`;
}

function capabilityLabel(status: "enabled" | "disabled" | "unsupported"): string {
  if (status === "enabled") {
    return "Đã bật";
  }
  if (status === "disabled") {
    return "Đã khóa";
  }
  return "Chưa hỗ trợ";
}

export function AdminDashboard({ state, onRetry }: AdminDashboardProps) {
  const [filterQuery, setFilterQuery] = useState("");
  const sourceLabel = state.supplier.kind === "ready" ? state.supplier.supplier : "backend";
  const modeLabel =
    state.supplier.kind === "ready"
      ? `${state.supplier.mode.toLocaleUpperCase("vi-VN")} · ${state.supplier.readOnly ? "READ-ONLY" : "UNKNOWN"}`
      : "ĐANG XÁC MINH";
  const normalizedQuery = filterQuery.trim().toLocaleLowerCase("vi-VN");
  const visibleItems =
    state.catalog.kind === "success"
      ? state.catalog.items.filter((item) =>
          [item.name, item.description, item.supplier].some((value) =>
            value.toLocaleLowerCase("vi-VN").includes(normalizedQuery),
          ),
        )
      : [];

  return (
    <main className="admin-dashboard" id="catalog-content">
      <header className="dashboard-heading">
        <div>
          <h1>Danh mục vận hành</h1>
          <p>
            Dữ liệu đi qua FastAPI từ nguồn {sourceLabel}. Giá hiển thị theo đơn vị minor và
            không tạo giao dịch.
          </p>
        </div>
        {state.catalog.kind === "success" && (
          <span className="dashboard-count">
            {normalizedQuery
              ? `${visibleItems.length}/${state.catalog.items.length} sản phẩm`
              : `${state.catalog.items.length} sản phẩm`}
          </span>
        )}
      </header>

      <div className="dashboard-layout">
        <section
          className="dashboard-catalog-state"
          aria-labelledby="catalog-section-title"
          aria-live="polite"
          aria-busy={state.catalog.kind === "loading"}
        >
          <h2 id="catalog-section-title">Catalog</h2>

          {state.catalog.kind === "loading" && (
            <div className="dashboard-state-panel" role="status">
              <strong>Đang tải catalog qua FastAPI…</strong>
              <span>Backend đang chuẩn bị dữ liệu tổng hợp.</span>
            </div>
          )}
          {state.catalog.kind === "error" && (
            <div className="dashboard-state-panel dashboard-state-panel-error" role="alert">
              <strong>Không đọc được catalog</strong>
              <span>{state.catalog.message}</span>
              {state.catalog.retryable && (
                <button type="button" onClick={onRetry}>
                  Thử lại
                </button>
              )}
            </div>
          )}
          {state.catalog.kind === "empty" && (
            <div className="dashboard-state-panel" role="status">
              <strong>Catalog đang trống.</strong>
              <span>Backend phản hồi thành công nhưng chưa có sản phẩm tổng hợp.</span>
            </div>
          )}
          {state.catalog.kind === "success" && (
            <div className="dashboard-catalog-success">
              {state.catalog.warning !== null && (
                <div className="dashboard-state-panel dashboard-state-panel-warning" role="status">
                  <strong>Đang hiển thị dữ liệu cache đã cũ</strong>
                  <span>{state.catalog.warning.message}</span>
                  {state.catalog.warning.retryable && (
                    <button type="button" onClick={onRetry}>
                      Làm mới
                    </button>
                  )}
                </div>
              )}

              <div className="dashboard-tools">
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
                <div className="dashboard-state-panel" role="status">
                  <strong>Không có sản phẩm phù hợp.</strong>
                  <span>Thử tên sản phẩm hoặc supplier khác.</span>
                </div>
              ) : (
                <div
                  className="dashboard-table-region"
                  tabIndex={0}
                  aria-label="Bảng danh mục chỉ đọc"
                >
                  <table className="dashboard-table">
                    <thead>
                      <tr>
                        <th scope="col">Sản phẩm</th>
                        <th scope="col">Supplier</th>
                        <th scope="col">Tồn kho</th>
                        <th scope="col">Giá</th>
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
                          <td data-label="Giá">{formatMinorMoney(item.price)}</td>
                          <td data-label="Trạng thái">
                            <span
                              className={
                                item.available_quantity > 0
                                  ? "dashboard-availability dashboard-availability-ready"
                                  : "dashboard-availability dashboard-availability-empty"
                              }
                            >
                              {item.available_quantity > 0 ? "Có sẵn" : "Hết hàng"}
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

        <aside className="dashboard-supplier-state" aria-labelledby="supplier-section-title">
          <h2 id="supplier-section-title">Supplier</h2>
          {state.supplier.kind === "loading" && (
            <div className="dashboard-state-panel" role="status">
              <strong>Đang đọc trạng thái supplier…</strong>
            </div>
          )}
          {state.supplier.kind === "error" && (
            <div className="dashboard-state-panel dashboard-state-panel-error" role="alert">
              <strong>Không đọc được trạng thái supplier</strong>
              <span>{state.supplier.message}</span>
              <button type="button" onClick={onRetry}>
                Thử lại
              </button>
            </div>
          )}
          {state.supplier.kind === "ready" && (
            <div className="dashboard-supplier-card">
              <dl>
                <div>
                  <dt>Nguồn</dt>
                  <dd>{state.supplier.supplier}</dd>
                </div>
                <div>
                  <dt>Chế độ</dt>
                  <dd>{modeLabel}</dd>
                </div>
                <div>
                  <dt>Tiền tệ catalog</dt>
                  <dd>
                    {state.supplier.currencies.length > 0
                      ? state.supplier.currencies.join(", ")
                      : "Chưa có dữ liệu"}
                  </dd>
                </div>
                <div>
                  <dt>Số dư</dt>
                  <dd>{state.supplier.balance.reason}</dd>
                </div>
              </dl>
              <h3>Biên an toàn</h3>
              <ul className="dashboard-capability-list">
                <li>
                  <span>Đọc catalog</span>
                  <strong>{capabilityLabel(state.supplier.capabilities.catalog_read.status)}</strong>
                </li>
                <li>
                  <span>Chi tiết catalog</span>
                  <strong>
                    {capabilityLabel(state.supplier.capabilities.catalog_detail.status)}
                  </strong>
                </li>
                <li>
                  <span>Mua hàng</span>
                  <strong>{capabilityLabel(state.supplier.capabilities.purchase.status)}</strong>
                </li>
                <li>
                  <span>Thanh toán</span>
                  <strong>{capabilityLabel(state.supplier.capabilities.payment.status)}</strong>
                </li>
                <li>
                  <span>Nạp tiền</span>
                  <strong>{capabilityLabel(state.supplier.capabilities.top_up.status)}</strong>
                </li>
                <li>
                  <span>Hoàn tiền / giao hàng</span>
                  <strong>
                    {capabilityLabel(state.supplier.capabilities.refund.status)} / {" "}
                    {capabilityLabel(state.supplier.capabilities.delivery.status)}
                  </strong>
                </li>
              </ul>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}
