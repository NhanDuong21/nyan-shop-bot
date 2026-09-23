import { useCatalogState } from "./catalog-state";
import type { CatalogSelection } from "./api";
import { AdminDashboard } from "./features/admin-dashboard/AdminDashboard";
import { ThemeToggle } from "./ThemeToggle";
import { useAdminTheme } from "./theme";

export function App() {
  const catalog = useCatalogState();
  const theme = useAdminTheme();
  const supplier = catalog.state.supplier;
  const environmentLabel =
    supplier.kind === "ready" ? supplier.mode.toLocaleUpperCase("vi-VN") : "LOADING";
  const isLiveRead = supplier.kind === "ready" && supplier.mode !== "mock";
  const supplierLabel =
    supplier.kind === "ready" && supplier.supplier === "aggregate"
      ? "KhoMMO + VietShare"
      : supplier.kind === "ready" && supplier.supplier === "khommo"
      ? "KhoMMO"
      : supplier.kind === "ready" && supplier.supplier === "vietshare"
        ? "VietShare"
        : "Supplier";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#catalog-content">
        Bỏ qua đến nội dung
      </a>
      <header className="app-bar">
        <div className="app-identity" aria-label="Nyan Shop Bot admin">
          <span className="app-mark" aria-hidden="true">
            N
          </span>
          <div>
            <strong>Nyan Shop Bot</strong>
            <span>Quản trị vận hành</span>
          </div>
        </div>
        <div className="app-actions">
          {catalog.sources.length > 1 && (
            <label className="source-selector">
              <span>Nguồn</span>
              <select
                aria-label="Chọn nguồn catalog"
                value={catalog.selectedSource ?? ""}
                onChange={(event) =>
                  catalog.selectSource(event.target.value as CatalogSelection)
                }
              >
                {catalog.aggregateAvailable && <option value="all">Tất cả nguồn</option>}
                {catalog.sources.map((source) => (
                  <option key={source.supplier} value={source.supplier}>
                    {source.supplier === "khommo" ? "KhoMMO" : "VietShare"}
                  </option>
                ))}
              </select>
            </label>
          )}
          <span className="environment-badge" aria-label={`Môi trường ${environmentLabel}`}>
            {environmentLabel}
          </span>
          <span className="environment-badge environment-badge-muted">READ-ONLY</span>
          <ThemeToggle theme={theme.theme} onToggle={theme.toggleTheme} />
        </div>
      </header>

      <aside className="environment-notice" role="note">
        <strong>Môi trường thử nghiệm chỉ chạy trên localhost.</strong>
        <span>
          {isLiveRead
            ? ` ${supplierLabel} chỉ cho phép đọc catalog; mua hàng, thanh toán và giao hàng vẫn bị khóa.`
            : " Không mua hàng, thanh toán hoặc gọi supplier thật."}
        </span>
      </aside>

      <AdminDashboard state={catalog.state} onRetry={catalog.retry} />
    </div>
  );
}
