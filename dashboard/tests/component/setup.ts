// Vitest setup file for the component-test harness (Phase 9.1, D11).
// Extends `expect` with the jest-dom matchers (toBeInTheDocument, etc.) for
// every test file matched by vitest.config.ts's `include`.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// `test.globals` is deliberately false (explicit imports everywhere), so RTL's
// automatic afterEach-cleanup registration never fires on its own — wire it up
// here instead. Without this, unmounted components leak across test cases in
// the same file and later queries (getByText etc.) start matching duplicates.
afterEach(() => {
  cleanup();
});
