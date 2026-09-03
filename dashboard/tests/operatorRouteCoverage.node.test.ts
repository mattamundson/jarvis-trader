import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import test from "node:test";

const script = path.resolve(process.cwd(), "scripts/audit-operator-route-coverage.mjs");

function audit() {
  const output = execFileSync(process.execPath, [script, "--json"], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  return JSON.parse(output) as {
    audit: string;
    authoritative: boolean;
    removal_authorized: boolean;
    current_route_count: number;
    unmapped_current_routes: string[];
    planned_canonical_routes_missing: string[];
    manifest_sources_not_present: string[];
  };
}

test("every current dashboard page has an explicit K-01 disposition", () => {
  const report = audit();
  assert.equal(report.audit, "JARVIS_K01_OPERATOR_ROUTE_COVERAGE");
  assert.ok(report.current_route_count >= 40);
  assert.deepEqual(report.unmapped_current_routes, []);
});

test("route coverage audit remains non-authoritative and non-destructive", () => {
  const report = audit();
  assert.equal(report.authoritative, false);
  assert.equal(report.removal_authorized, false);
});

test("planned IA and harvest-only sources remain visible as migration debt", () => {
  const report = audit();
  assert.ok(report.planned_canonical_routes_missing.includes("/risk"));
  assert.ok(report.planned_canonical_routes_missing.includes("/audit"));
  assert.ok(report.manifest_sources_not_present.includes("/command-center-v2"));
});
