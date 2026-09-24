import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:15175",
    browserName: "chromium",
    channel: process.platform === "win32" ? "msedge" : undefined,
    headless: true,
  },
  webServer: {
    command: "npm run dev -- --port 15175",
    url: "http://127.0.0.1:15175",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
