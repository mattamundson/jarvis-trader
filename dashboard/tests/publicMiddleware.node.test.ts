import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { NextRequest } from "next/server.js";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../middleware.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText.replace('"next/server"', JSON.stringify(pathToFileURL(require.resolve("next/server.js")).href));
const { middleware } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("actual middleware challenges every page, API, and WebSocket request", () => {
  const saved = { ...process.env };
  try {
    process.env.VERCEL = "1";
    process.env.DASHBOARD_AUTH_USER = "owner-test";
    process.env.DASHBOARD_AUTH_PASS = "test-only-value";
    for (const path of ["/", "/ops", "/mission-control", "/market-brief-public",
      "/api/engine/portfolio/summary", "/api/engine/journal/entries", "/api/flow"]) {
      const response = middleware(new NextRequest(`https://example.invalid${path}`));
      assert.equal(response.status, 401, path);
      assert.match(response.headers.get("www-authenticate"), /^Basic /);
    }
    const ws = middleware(new NextRequest("https://example.invalid/ws/events", { headers: { upgrade: "websocket" } }));
    assert.equal(ws.status, 401);
    assert.equal(ws.headers.has("www-authenticate"), false);
  } finally {
    for (const key of ["VERCEL", "DASHBOARD_AUTH_USER", "DASHBOARD_AUTH_PASS"]) {
      if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key];
    }
  }
});

test("legacy demo flag cannot make hosted actions public", () => {
  const saved = { ...process.env };
  try {
    process.env.VERCEL = "1";
    process.env.DASHBOARD_AUTH_DISABLED = "1";
    delete process.env.DASHBOARD_AUTH_USER;
    delete process.env.DASHBOARD_AUTH_PASS;
    const response = middleware(new NextRequest("https://example.invalid/api/engine/halt", {
      method: "POST", headers: { authorization: "Basic invalid" },
    }));
    assert.equal(response.status, 503);
  } finally {
    for (const key of ["VERCEL", "DASHBOARD_AUTH_DISABLED", "DASHBOARD_AUTH_USER", "DASHBOARD_AUTH_PASS"]) {
      if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key];
    }
  }
});

test("owner sign-in explicitly challenges; valid owner credentials unlock the route", () => {
  const saved = { ...process.env };
  try {
    process.env.VERCEL = "1";
    process.env.DASHBOARD_AUTH_USER = "owner-test";
    process.env.DASHBOARD_AUTH_PASS = "test-only-value";
    const request = new NextRequest("https://example.invalid/api/owner-sign-in");
    const challenge = middleware(request);
    assert.equal(challenge.status, 401);
    assert.match(challenge.headers.get("www-authenticate"), /^Basic /);
    const auth = `Basic ${Buffer.from("owner-test:test-only-value").toString("base64")}`;
    assert.equal(middleware(new NextRequest(request.url, { headers: { authorization: auth } })).status, 200);
    assert.equal(middleware(new NextRequest("https://example.invalid/api/engine/journal/entries", {
      method: "POST", headers: { authorization: auth },
    })).status, 200);
  } finally {
    for (const key of ["VERCEL", "DASHBOARD_AUTH_USER", "DASHBOARD_AUTH_PASS"]) {
      if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key];
    }
  }
});
