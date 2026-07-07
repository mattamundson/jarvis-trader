import { defineConfig } from "@playwright/test";

// Golden-path e2e. Uses the pre-installed Chromium (no browser download).
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
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
    reuseExistingServer: true,
  },
});
