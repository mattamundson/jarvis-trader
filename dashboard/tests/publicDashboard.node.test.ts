import assert from "node:assert/strict";
import { test } from "node:test";
import { ROUTES } from "./e2e/_routes.ts";
import { isPublicReadOnlyRequest } from "../lib/publicRoutes.ts";

test("every dashboard page requires credentials for reads and writes", () => {
  for (const { path } of ROUTES) {
    for (const method of ["GET", "HEAD", "POST"]) {
      assert.equal(isPublicReadOnlyRequest(path, method), false, `${method} ${path}`);
    }
  }
});
test("all data APIs remain private", () => {
  for (const path of ["/api/flow", "/api/engine/health", "/api/engine/portfolio/summary",
    "/api/engine/journal/entries", "/api/master/master/finances/detail", "/api/public-market-brief/latest", "/ws/events"]) {
    assert.equal(isPublicReadOnlyRequest(path, "GET"), false, path);
  }
});
