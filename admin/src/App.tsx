import { useCatalogState } from "./catalog-state";
import { AdminDashboard } from "./features/admin-dashboard/AdminDashboard";
import { ThemeToggle } from "./ThemeToggle";
import { useAdminTheme } from "./theme";

export function App() {
  const catalog = useCatalogState();
  const theme = useAdminTheme();

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
          <span className="environment-badge" aria-label="Môi trường mock">
            MOCK
          </span>
          <span className="environment-badge environment-badge-muted">READ-ONLY</span>
          <ThemeToggle theme={theme.theme} onToggle={theme.toggleTheme} />
        </div>
      </header>

      <aside className="environment-notice" role="note">
        <strong>Môi trường thử nghiệm chỉ chạy trên localhost.</strong>
        <span> Không mua hàng, thanh toán hoặc gọi supplier thật.</span>
      </aside>

      <AdminDashboard state={catalog.state} onRetry={catalog.retry} />
    </div>
  );
}
