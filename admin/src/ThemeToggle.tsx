import type { Theme } from "./theme";

interface ThemeToggleProps {
  theme: Theme;
  onToggle: () => void;
}

export function ThemeToggle({ theme, onToggle }: ThemeToggleProps) {
  const nextTheme = theme === "light" ? "tối" : "sáng";

  return (
    <button
      className="theme-toggle"
      type="button"
      aria-label={`Chuyển sang giao diện ${nextTheme}`}
      aria-pressed={theme === "dark"}
      onClick={onToggle}
    >
      <span>Giao diện</span>
      <strong>{theme === "light" ? "Sáng" : "Tối"}</strong>
    </button>
  );
}
