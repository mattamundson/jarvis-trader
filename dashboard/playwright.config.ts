import { defineConfig } from "@playwright/test";

// Golden-path e2e. Uses the pre-installed Chromium (no browser download).
//
// SERVER REUSE -- read before changing.
//   This config previously set `reuseExistingServer: true` UNCONDITIONALLY on
//   port 3010. On this machine 3010 is pm2's PRODUCTION dashboard, so a local
//   run silently tested whatever pm2 was already serving instead of the build
//   under test. A green run in that mode is not evidence: it can pass against a
//   build that predates the change being verified.
//
//   Reuse is now disabled in CI explicitly rather than by luck (CI has no
//   pre-existing server, but relying on that was an accident, not a design).
//
//   For any E2E claim that gates a commit, PR, or deploy, use the fresh variant
//   instead -- it binds a port pm2 does not own and never reuses:
//
//       pnpm run test:e2e:fresh        (playwright.fresh.config.ts, port 3013)

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  // Kept at 0 deliberately: a flaky test on a trading dashboard is real signal,
  // not noise to be retried away.
  retries: 0,
  use: {
    baseURL: "http://localhost:3010",
    launchOptions: {
      executablePath: process.env.PW_CHROME || undefined,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
  },
  webServer: {
    command: "pnpm exec next start -p 3010",
    url: "http://localhost:3010",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
});
