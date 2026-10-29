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

test("actual middleware permits viewing but blocks anonymous actions without browser login prompts", () => {
  for (const path of ["/ops", "/mission-control", "/api/engine/portfolio/summary", "/api/engine/journal/entries"]) {
    assert.equal(middleware(new NextRequest(`https://example.invalid${path}`)).status, 200, path);
  }
  for (const [path, method] of [
    ["/api/engine/portfolio/halt", "POST"], ["/api/engine/settings/risk", "PUT"],
    ["/api/master/master/command/stream?text=halt", "GET"], ["/api/engine/jarvis/analyze", "GET"],
    ["/api/engine/unknown", "GET"], ["/api/engine/journal/entries", "DELETE"],
  ]) {
    const response = middleware(new NextRequest(`https://example.invalid${path}`, { method }));
    assert.equal(response.status, 403, `${method} ${path}`);
    assert.equal(response.headers.has("www-authenticate"), false);
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
