import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { isPublicReadOnlyRequest } from "../lib/publicRoutes.ts";

test("home and its feed permit anonymous reads only", () => {
  for (const path of ["/", "/api/flow"]) {
    for (const method of ["GET", "HEAD"]) assert.equal(isPublicReadOnlyRequest(path, method), true);
    for (const method of ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]) {
      assert.equal(isPublicReadOnlyRequest(path, method), false);
    }
  }
});

test("private pages, ingest and all engine routes remain authenticated", () => {
  for (const path of ["/ops", "/mission-control", "/api/flow/ingest", "/api/flow/anything",
    "/api/engine/health", "/api/engine/halt", "/api/master/status", "/ws/events"]) {
    for (const method of ["GET", "HEAD", "POST", "DELETE"]) {
      assert.equal(isPublicReadOnlyRequest(path, method), false, `${method} ${path}`);
    }
  }
});

test("public home uses the display-only shell before private providers mount", () => {
  const shell = readFileSync(new URL("../components/AppShell.tsx", import.meta.url), "utf8");
  assert.match(shell, /return pathname === "\/" \|\| pathname === "\/market-brief-public"/);
  assert.ok(shell.indexOf("if (isPublicReadOnlyPath(pathname))") < shell.indexOf("<EngineWebSocketProvider>"));
});
