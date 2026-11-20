import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

test("proxy error responses do not leak internal paths (ngrok, C:\\Users, /var/task)", async () => {
  const { default: ts } = await import("typescript");
  const { createRequire } = await import("node:module");
  const { pathToFileURL } = await import("node:url");
  const require = createRequire(import.meta.url);
  const { NextRequest } = await import("next/server.js");
  const originalFetch = globalThis.fetch;

  try {
    // Simulate network error that would previously leak target URL
    globalThis.fetch = async () => {
      throw new Error("Network error: connection refused");
    };

    for (const service of ["engine", "master"]) {
      const source = readFileSync(
        new URL(`../app/api/${service}/[...path]/route.ts`, import.meta.url),
        "utf8"
      );

      const code = ts
        .transpileModule(source, {
          compilerOptions: {
            module: ts.ModuleKind.ESNext,
            target: ts.ScriptTarget.ES2022,
          },
        })
        .outputText.replace(
          '"next/server"',
          JSON.stringify(pathToFileURL(require.resolve("next/server.js")).href)
        );

      const { GET } = await import(
        `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
      );
      const result = await GET(
        new NextRequest(`https://example.invalid/api/${service}/health`),
        {
          params: Promise.resolve({ path: ["health"] }),
        }
      );

      assert.equal(result.status, 502, `${service} should return 502 on fetch error`);
      const json = await result.json();
      assert.equal(
        json.error,
        `${service}_proxy_failed`,
        `${service} error field should match`
      );

      // Verify that the 'target' field is NOT present in the error response
      assert.equal(
        json.hasOwnProperty("target"),
        false,
        `${service} error response must not leak target URL`
      );

      // Verify that internal paths are not in the message either
      assert.doesNotMatch(
        json.message || "",
        /ngrok\.io/i,
        `${service} must not leak ngrok hostname`
      );
      assert.doesNotMatch(
        json.message || "",
        /C:\\Users/i,
        `${service} must not leak Windows paths`
      );
      assert.doesNotMatch(
        json.message || "",
        /\/var\/task/,
        `${service} must not leak Lambda paths`
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("proxy sources no longer include target URL in error responses", () => {
  for (const service of ["engine", "master"]) {
    const source = readFileSync(
      new URL(`../app/api/${service}/[...path]/route.ts`, import.meta.url),
      "utf8"
    );

    // Verify that the error construction no longer includes target: target.toString()
    assert.doesNotMatch(
      source,
      /target:\s*target\.toString\(\)/,
      `${service} proxy source should not include target URL in error response`
    );
  }
});
