import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const manifestPath = path.resolve(process.cwd(), "config/operator-route-migration.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
  plan: string;
  work_package: string;
  schema_version: number;
  authoritative: boolean;
  removal_authorized: boolean;
  canonical_surfaces: Array<{ name: string; route: string; state: string }>;
  transitional_targets: string[];
  migrations: Array<{ source: string; target: string; status: string; reason?: string }>;
};

const allowedSurfaceStates = new Set(["ACTIVE", "PLANNED"]);
const allowedMigrationStates = new Set([
  "ACTIVE",
  "MAPPED",
  "FEATURE_PARITY_PROVEN",
  "REDIRECTED",
  "DEPRECATED",
  "REMOVED",
]);

function unique(values: string[]): boolean {
  return new Set(values).size === values.length;
}

test("K-01 manifest remains explicitly non-authoritative and non-destructive", () => {
  assert.equal(manifest.plan, "JARVIS-MIP-1.0");
  assert.equal(manifest.work_package, "K-01");
  assert.equal(manifest.schema_version, 1);
  assert.equal(manifest.authoritative, false);
  assert.equal(manifest.removal_authorized, false);
  assert.equal(manifest.migrations.some((row) => row.status === "REMOVED"), false);
});

test("canonical operator surfaces are unique and well-formed", () => {
  const names = manifest.canonical_surfaces.map((row) => row.name);
  const routes = manifest.canonical_surfaces.map((row) => row.route);

  assert.ok(unique(names));
  assert.ok(unique(routes));
  for (const row of manifest.canonical_surfaces) {
    assert.ok(row.name.length > 0);
    assert.ok(row.route.startsWith("/"));
    assert.ok(allowedSurfaceStates.has(row.state));
  }
});

test("migration sources are unique and targets are explicit", () => {
  const sources = manifest.migrations.map((row) => row.source);
  assert.ok(unique(sources));

  const canonicalRoutes = new Set(manifest.canonical_surfaces.map((row) => row.route));
  const transitionalTargets = new Set(manifest.transitional_targets);

  for (const row of manifest.migrations) {
    assert.ok(row.source.startsWith("/"));
    assert.ok(row.target.startsWith("/"));
    assert.ok(allowedMigrationStates.has(row.status));
    assert.ok(
      canonicalRoutes.has(row.target) || transitionalTargets.has(row.target),
      `migration target must be canonical or explicitly transitional: ${row.target}`,
    );
  }
});

test("command-center-v2 is harvest-only and cannot become a second canonical command center", () => {
  const migration = manifest.migrations.find((row) => row.source === "/command-center-v2");
  assert.ok(migration);
  assert.equal(migration.target, "/command-center");
  assert.equal(migration.status, "MAPPED");
  assert.match(migration.reason ?? "", /harvest source/i);
  assert.equal(
    manifest.canonical_surfaces.some((row) => row.route === "/command-center-v2"),
    false,
  );
});

test("performance is named as transitional rather than silently promoted to canonical IA", () => {
  assert.deepEqual(manifest.transitional_targets, ["/performance"]);
  assert.equal(
    manifest.canonical_surfaces.some((row) => row.route === "/performance"),
    false,
  );
});
