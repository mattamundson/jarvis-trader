import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Vitest + React Testing Library + jsdom component-test harness (Phase 9.1, D11).
//
// This coexists with the EXISTING `pnpm test:unit` (node:test) runner, which
// covers `tests/**/*.node.test.ts` — pure-logic/formatter tests with zero DOM.
// This config is scoped ONLY to `tests/component/**` so the two runners never
// pick up each other's files.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/component/**/*.test.tsx", "tests/component/**/*.test.ts"],
    setupFiles: ["./tests/component/setup.ts"],
    globals: false,
    css: false,
  },
});
