import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}", "vite.config.ts"],
    languageOptions: {
      globals: {
        AbortController: "readonly",
        document: "readonly",
        fetch: "readonly",
        HTMLElement: "readonly",
        Intl: "readonly",
        RequestInfo: "readonly",
        RequestInit: "readonly",
        Response: "readonly",
      },
    },
  },
);
