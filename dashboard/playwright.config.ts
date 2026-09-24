import fs from "node:fs";
import path from "node:path";

import { defineConfig } from "@playwright/test";

function loadDashboardBasicAuthEnv(): void {
  const envPath = path.join(__dirname, ".env.local");
  if (!fs.existsSync(envPath)) return;

  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;

    const key = trimmed.slice(0, eq).trim();
    if (key !== "DASHBOARD_AUTH_USER" && key !== "DASHBOARD_AUTH_PASS") continue;

    const rawValue = trimmed.slice(eq + 1).trim();
    const value = rawValue.replace(/^['\"]|['\"]$/g, "");
    if (!process.env[key]) {
      process.env[key] = value;
    }
  }
}

loadDashboardBasicAuthEnv();

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

// PROJECT SPLIT -- read before changing `workers`.
//
//   smoke       - the table-driven suite over every manifest route (91 cases at
//                 50 routes). Parallel, because serial it dominates the wall
//                 clock of `Dashboard Build (Next.js)` -- a REQUIRED status
//                 check on master. This is not an ergonomics preference; at
//                 workers:1 the required check becomes the slowest thing in CI.
//   golden-path - the hand-written domain specs. These predate the split and
//                 were authored under workers:1.
//
// Playwright has no per-project worker count, so `workers` is global. Tests
// within a golden-path file still run in declaration order (fullyParallel:false),
// but separate golden-path FILES can now run concurrently. They are read-only
// page loads against a mocked engine, so that should be safe -- if it turns out
// not to be, the interference is a real finding about shared state, not a reason
// to quietly go back to workers:1.
// PORT -- read before changing.
//   3010 is pm2's PRODUCTION dashboard on this machine. Two independent hazards
//   follow from that, both of which previously produced misleading green runs:
//
//   1. Reuse. `reuseExistingServer: true` meant a local run silently tested
//      whatever pm2 was already serving (a build that can predate the change under
//      verification) instead of the build in the working tree. Stale-server reuse
//      is now OPT-IN only, via PW_REUSE_SERVER=1, and never the default. When 3010
//      is occupied and reuse is off, Playwright fails loudly ("port already used")
//      -- that is the correct outcome, and the fix is to stop pm2 or set PW_PORT.
//
//   2. Port collision. Because pm2 owns 3010, a fresh-server local run cannot bind
//      it. PW_PORT overrides the port (e.g. PW_PORT=3013) so a local run can build
//      and serve its own instance without touching pm2. CI leaves it unset and keeps
//      using 3010, where no server is running.
const PORT = Number(process.env.PW_PORT ?? 3010);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 4,
  // Kept at 0 deliberately: a flaky test on a trading dashboard is real signal,
  // not noise to be retried away.
  retries: 0,
  projects: [
    {
      name: "smoke",
      testMatch: /smoke\.spec\.ts$/,
      fullyParallel: true,
    },
    {
      name: "golden-path",
      testIgnore: /smoke\.spec\.ts$/,
      fullyParallel: false,
    },
  ],
  use: {
    baseURL: `http://localhost:${PORT}`,
    httpCredentials:
      process.env.DASHBOARD_AUTH_USER && process.env.DASHBOARD_AUTH_PASS
        ? {
            username: process.env.DASHBOARD_AUTH_USER,
            password: process.env.DASHBOARD_AUTH_PASS,
          }
        : undefined,
    launchOptions: {
      executablePath: process.env.PW_CHROME || undefined,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
  },
  webServer: {
    command: `pnpm exec next start -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    timeout: 120_000,
    // Opt-in only. Default false means every run exercises the build in the
    // working tree; see the PORT note above for why that matters on this machine.
    reuseExistingServer: process.env.PW_REUSE_SERVER === "1",
  },
});
