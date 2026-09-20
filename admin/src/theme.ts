import { useCallback, useLayoutEffect, useState } from "react";

export const THEME_STORAGE_KEY = "nyan-admin-theme";

export type Theme = "light" | "dark";

interface ThemeStorage {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

function browserStorage(): ThemeStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isTheme(value: string | null): value is Theme {
  return value === "light" || value === "dark";
}

export function readTheme(storage: ThemeStorage | null = browserStorage()): Theme {
  try {
    const savedTheme = storage?.getItem(THEME_STORAGE_KEY) ?? null;
    return isTheme(savedTheme) ? savedTheme : "light";
  } catch {
    return "light";
  }
}

export function persistTheme(
  requestedTheme: Theme,
  storage: ThemeStorage | null = browserStorage(),
): Theme {
  try {
    if (!storage) {
      return "light";
    }
    storage.setItem(THEME_STORAGE_KEY, requestedTheme);
    return requestedTheme;
  } catch {
    return "light";
  }
}

export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  root.dataset.theme = theme;
  root.style.colorScheme = theme;

  const colorScheme = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
  if (colorScheme) {
    colorScheme.content = theme;
  }
}

export interface ThemeController {
  theme: Theme;
  chooseTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

export function useAdminTheme(): ThemeController {
  const [theme, setTheme] = useState<Theme>(() => readTheme());

  useLayoutEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const chooseTheme = useCallback((requestedTheme: Theme) => {
    const safeTheme = persistTheme(requestedTheme);
    applyTheme(safeTheme);
    setTheme(safeTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    chooseTheme(theme === "light" ? "dark" : "light");
  }, [chooseTheme, theme]);

  return { theme, chooseTheme, toggleTheme };
}
