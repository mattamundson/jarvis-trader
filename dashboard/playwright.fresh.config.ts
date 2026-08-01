import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// The variant that produces TRUSTWORTHY local E2E results.
//
// The default config reuses an existing server on 3010 -- which on this machine
// is pm2's PRODUCTION dashboard. A run in that mode can pass against a build
// that predates the change being verified, so "E2E green" from it is not
// evidence of anything.
//
// This config binds a dedicated port that pm2 does not own and refuses to reuse
// any running server, so the suite is guaranteed to exercise the current build.
//
// Use this -- `pnpm run test:e2e:fresh` -- for any E2E claim that gates a
// commit, a PR, or a deploy.
//
// Implemented as a config file rather than an env var deliberately: setting
// env vars inline is not portable across cmd/PowerShell/sh, and `cross-env` is
// NOT installed in this project despite package.json's build:analyze script
// already referencing it (that script is broken on master for the same reason).

const PORT = 3013;
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  ...base,
  use: {
    ...base.use,
    baseURL: BASE_URL,
  },
  webServer: {
    command: `pnpm exec next start -p ${PORT}`,
    url: BASE_URL,
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
