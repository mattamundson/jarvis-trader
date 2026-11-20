import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { upstreamAuthFailure } from "../lib/upstreamAuth.ts";
import { applyEngineAuthHeaders } from "../lib/engineProxyHeaders.ts";

test("backend auth failures report a connection error, never a dashboard login challenge", async () => {
  for (const status of [401, 403]) {
    const response = upstreamAuthFailure(status, "engine")!;
    assert.equal(response.status, 502);
    assert.equal(response.headers.has("www-authenticate"), false);
    assert.equal((await response.json()).error, "upstream_auth_failed");
  }
  for (const status of [200, 404, 500]) assert.equal(upstreamAuthFailure(status, "engine"), null);
});
test("every backend proxy removes backend login challenges", () => {
  for (const service of ["engine", "master", "amo", "domflow"]) {
    const source = readFileSync(new URL(`../app/api/${service}/[...path]/route.ts`, import.meta.url), "utf8");
    assert.match(source, /upstreamAuthFailure\(upstream.status/);
    assert.match(source, /responseHeaders.delete\("www-authenticate"\)/);
  }
});
test("dashboard Authorization never leaks to the engine when no tunnel auth is configured", () => {
  const headers = applyEngineAuthHeaders(new Headers({ authorization: "Basic dashboard-test" }), {});
  assert.equal(headers.has("authorization"), false);
});

test("actual proxy handlers return 502 without prompting when backend returns 401", async () => {
  const { default: ts } = await import("typescript");
  const { createRequire } = await import("node:module");
  const { pathToFileURL } = await import("node:url");
  const require = createRequire(import.meta.url);
  const { NextRequest } = await import("next/server.js");
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response("Backend unauthorized", {
      status: 401, headers: { "WWW-Authenticate": 'Basic realm="backend"' },
    });
    for (const service of ["engine", "master", "amo", "domflow"]) {
      const source = readFileSync(new URL(`../app/api/${service}/[...path]/route.ts`, import.meta.url), "utf8");
      const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
        .replace('"next/server"', JSON.stringify(pathToFileURL(require.resolve("next/server.js")).href));
      const { GET } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
      const result = await GET(new NextRequest(`https://example.invalid/api/${service}/health`), {
        params: Promise.resolve({ path: ["health"] }),
      });
      assert.equal(result.status, 502, service);
      assert.equal(result.headers.has("www-authenticate"), false, service);
      assert.equal((await result.json()).error, "upstream_auth_failed", service);
    }
  } finally { globalThis.fetch = originalFetch; }
});
