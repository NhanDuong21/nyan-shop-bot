import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import indexHtml from "../index.html?raw";
import { ThemeToggle } from "./ThemeToggle";
import { THEME_STORAGE_KEY, useAdminTheme } from "./theme";

function ThemeHarness() {
  const theme = useAdminTheme();

  return <ThemeToggle theme={theme.theme} onToggle={theme.toggleTheme} />;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  document.documentElement.dataset.theme = "light";
  document.documentElement.style.colorScheme = "light";
});

test("defaults to light even when the operating system prefers dark", () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({ matches: true, media: "(prefers-color-scheme: dark)" }),
  );

  render(<ThemeHarness />);

  expect(document.documentElement.dataset.theme).toBe("light");
  expect(screen.getByRole("button", { name: /chuyển sang giao diện tối/i })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

test("persists an explicit choice and restores it on the next mount", () => {
  const firstRender = render(<ThemeHarness />);

  fireEvent.click(screen.getByRole("button", { name: /chuyển sang giao diện tối/i }));

  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");

  firstRender.unmount();
  document.documentElement.dataset.theme = "light";
  render(<ThemeHarness />);

  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(screen.getByRole("button", { name: /chuyển sang giao diện sáng/i })).toBeInTheDocument();
});

test("falls back to light when preference reading fails", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });

  render(<ThemeHarness />);

  expect(document.documentElement.dataset.theme).toBe("light");
});

test("falls back to light when a dark preference cannot be saved", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });

  render(<ThemeHarness />);
  fireEvent.click(screen.getByRole("button", { name: /chuyển sang giao diện tối/i }));

  expect(document.documentElement.dataset.theme).toBe("light");
  expect(screen.getByRole("button", { name: /chuyển sang giao diện tối/i })).toBeInTheDocument();
});

test("sets the light default before the application module can paint", () => {
  const htmlTag = indexHtml.indexOf('data-theme="light"');
  const bootstrap = indexHtml.indexOf('id="theme-bootstrap"');
  const applicationModule = indexHtml.indexOf('src="/src/main.tsx"');

  expect(htmlTag).toBeGreaterThan(-1);
  expect(bootstrap).toBeGreaterThan(htmlTag);
  expect(applicationModule).toBeGreaterThan(bootstrap);
  expect(indexHtml).toContain(`const storageKey = "${THEME_STORAGE_KEY}"`);
  expect(indexHtml).toContain("theme = \"light\"");
});
