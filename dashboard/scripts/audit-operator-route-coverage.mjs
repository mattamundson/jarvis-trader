#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const dashboardRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const appRoot = path.join(dashboardRoot, "app");
const manifestPath = path.join(dashboardRoot, "config", "operator-route-migration.json");

function walk(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (entry.isFile() && entry.name === "page.tsx") results.push(full);
  }
  return results;
}

export function pagePathToRoute(filePath, root = appRoot) {
  const relative = path.relative(root, path.dirname(filePath));
  if (!relative) return "/";
  const segments = relative
    .split(path.sep)
    .filter((segment) => !segment.startsWith("(") && !segment.startsWith("@"));
  return `/${segments.join("/")}`;
}

export function auditRoutes({ root = appRoot, manifestFile = manifestPath } = {}) {
  const manifest = JSON.parse(fs.readFileSync(manifestFile, "utf8"));
  const currentRoutes = [...new Set(walk(root).map((file) => pagePathToRoute(file, root)))].sort();
  const canonical = new Set(manifest.canonical_surfaces.map((row) => row.route));
  const transitional = new Set(manifest.transitional_targets ?? []);
  const migrations = new Map(manifest.migrations.map((row) => [row.source, row]));
  const covered = new Set([...canonical, ...transitional, ...migrations.keys()]);
  const currentSet = new Set(currentRoutes);

  return {
    audit: "JARVIS_K01_OPERATOR_ROUTE_COVERAGE",
    schema_version: 1,
    authoritative: manifest.authoritative === true,
    removal_authorized: manifest.removal_authorized === true,
    current_route_count: currentRoutes.length,
    current_routes: currentRoutes,
    unmapped_current_routes: currentRoutes.filter((route) => !covered.has(route)),
    planned_canonical_routes_missing: [...canonical].filter((route) => !currentSet.has(route)).sort(),
    manifest_sources_not_present: [...migrations.keys()].filter((route) => !currentSet.has(route)).sort(),
    migration_status_counts: manifest.migrations.reduce((acc, row) => {
      acc[row.status] = (acc[row.status] ?? 0) + 1;
      return acc;
    }, {}),
  };
}

function main() {
  const json = process.argv.includes("--json");
  const strict = process.argv.includes("--strict");
  const report = auditRoutes();
  if (json) console.log(JSON.stringify(report, null, 2));
  else {
    console.log("K-01 operator route coverage");
    console.log(`Current routes: ${report.current_route_count}`);
    console.log(`Unmapped current routes: ${report.unmapped_current_routes.length}`);
    for (const route of report.unmapped_current_routes) console.log(`[UNMAPPED] ${route}`);
    console.log(`Planned canonical routes not built: ${report.planned_canonical_routes_missing.length}`);
    console.log(`Manifest-only/harvest sources: ${report.manifest_sources_not_present.length}`);
    console.log(`Route removal authorized: ${report.removal_authorized}`);
  }
  process.exitCode = strict && report.unmapped_current_routes.length ? 2 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  main();
}
