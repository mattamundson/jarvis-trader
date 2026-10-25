import assert from "node:assert/strict";
import { test } from "node:test";

import { decideDashboardAuth, readDashboardAuthEnv } from "@/lib/dashboardAuth";

test("credentials present -> enforce Basic Auth", () => {
  assert.equal(decideDashboardAuth({ user: "amo", pass: "s3cret" }), "enforce");
});

test("hosted deployment without credentials -> FAIL CLOSED", () => {
  // The incident case: a Vercel deploy with no DASHBOARD_AUTH_* previously served
  // the whole dashboard and the engine proxy to the public internet.
  assert.equal(decideDashboardAuth({ vercel: "1" }), "deny");
});

test("hosted deployment with only one credential -> FAIL CLOSED", () => {
  assert.equal(decideDashboardAuth({ user: "amo", vercel: "1" }), "deny");
  assert.equal(decideDashboardAuth({ pass: "s3cret", vercel: "1" }), "deny");
});

test("plain localhost without credentials -> allowed for dev", () => {
  assert.equal(decideDashboardAuth({}), "allow");
  assert.equal(decideDashboardAuth({ vercel: "0" }), "allow");
});

test("explicit DASHBOARD_AUTH_DISABLED=1 -> allowed even when hosted", () => {
  assert.equal(decideDashboardAuth({ disabled: "1", vercel: "1" }), "allow");
});

test("configured credentials beat the disable flag", () => {
  assert.equal(decideDashboardAuth({ user: "amo", pass: "s3cret", disabled: "1", vercel: "1" }), "enforce");
});

test("disable flag must be exactly '1' to opt out", () => {
  assert.equal(decideDashboardAuth({ disabled: "true", vercel: "1" }), "deny");
  assert.equal(decideDashboardAuth({ disabled: "0", vercel: "1" }), "deny");
});

test("readDashboardAuthEnv maps the real environment variable names", () => {
  const mapped = readDashboardAuthEnv({
    DASHBOARD_AUTH_USER: "amo",
    DASHBOARD_AUTH_PASS: "s3cret",
    DASHBOARD_AUTH_DISABLED: "1",
    VERCEL: "1",
  } as unknown as NodeJS.ProcessEnv);
  assert.deepEqual(mapped, { user: "amo", pass: "s3cret", disabled: "1", vercel: "1" });
});

test("readDashboardAuthEnv tolerates an empty environment", () => {
  const mapped = readDashboardAuthEnv({} as unknown as NodeJS.ProcessEnv);
  assert.deepEqual(mapped, { user: undefined, pass: undefined, disabled: undefined, vercel: undefined });
  assert.equal(decideDashboardAuth(mapped), "allow");
});
