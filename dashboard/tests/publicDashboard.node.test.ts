import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { ROUTES } from "./e2e/_routes.ts";
import { isPublicReadOnlyRequest } from "../lib/publicRoutes.ts";

test("home and its feed permit anonymous reads only", () => {
  for (const path of ["/", "/api/flow"]) {
    for (const method of ["GET", "HEAD"]) assert.equal(isPublicReadOnlyRequest(path, method), true);
    for (const method of ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]) {
      assert.equal(isPublicReadOnlyRequest(path, method), false);
    }
  }
});

test("all pages and financial and journal reads are public; writes are not", () => {
  for (const path of ["/ops", "/mission-control", "/settings", "/journal", "/master/finances",
    "/api/engine/health", "/api/engine/portfolio/summary", "/api/engine/journal/entries",
    "/api/master/master/finances/detail"]) {
    assert.equal(isPublicReadOnlyRequest(path, "GET"), true, path);
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      assert.equal(isPublicReadOnlyRequest(path, method), false, `${method} ${path}`);
    }
  }
});

test("GET actions, unknown APIs, encoded paths, and WebSockets are not public reads", () => {
  for (const path of ["/api/flow/ingest", "/api/flow/anything", "/api/engine/halt",
    "/api/engine/portfolio/halt", "/api/engine/jarvis/analyze", "/api/engine/discord/bookmarks/weekly-themes",
    "/api/master/master/command/stream", "/api/cron/check-flow", "/api/engine/unknown",
    "/api/engine/decisions/%2e%2e%2fhalt/detail", "/ws/events"]) {
    assert.equal(isPublicReadOnlyRequest(path, "GET"), false, path);
  }
});

test("dashboard navigation remains available with a public-read-only notice", () => {
  const shell = readFileSync(new URL("../components/AppShell.tsx", import.meta.url), "utf8");
  assert.match(shell, /<Sidebar/);
  assert.match(shell, /Public read-only dashboard/);
});

test("every dashboard page in the route manifest is publicly readable, never writable", () => {
  for (const { path } of ROUTES) {
    assert.equal(isPublicReadOnlyRequest(path, "GET"), true, path);
    assert.equal(isPublicReadOnlyRequest(path, "POST"), false, path);
  }
});
