// Behavioral test for the engine proxy's auth-header injection.
//
// Unlike the tsc-only type tests elsewhere in this dir, this EXERCISES the runtime
// logic and asserts the actual headers. Runs on Node's built-in test runner (no new
// dependency):
//   cd dashboard && node --test --experimental-strip-types tests/engineProxyHeaders.test.ts
//
// Guards the 2026-07-06 incident: the proxy was shipped without the tunnel headers
// and reported "verified" on a tsc pass alone. This test is what "verified" means.

import { test } from "node:test";
import assert from "node:assert/strict";
import { applyEngineAuthHeaders } from "../lib/engineProxyHeaders.ts";

test("injects X-API-Key when apiKey present", () => {
  const h = applyEngineAuthHeaders(new Headers(), { apiKey: "key-123" });
  assert.equal(h.get("x-api-key"), "key-123");
});

test("omits X-API-Key when apiKey absent", () => {
  const h = applyEngineAuthHeaders(new Headers(), {});
  assert.equal(h.get("x-api-key"), null);
});

test("injects Authorization: Basic base64(user:pass) from tunnelBasicAuth", () => {
  const h = applyEngineAuthHeaders(new Headers(), { tunnelBasicAuth: "jarvis:s3cret" });
  const expected = "Basic " + Buffer.from("jarvis:s3cret").toString("base64");
  assert.equal(h.get("authorization"), expected);
  // sanity: decodes back to the original credential
  const decoded = Buffer.from(h.get("authorization")!.slice("Basic ".length), "base64").toString();
  assert.equal(decoded, "jarvis:s3cret");
});

test("omits Authorization when tunnelBasicAuth absent (local dev, no tunnel)", () => {
  const h = applyEngineAuthHeaders(new Headers(), { apiKey: "key-123" });
  assert.equal(h.get("authorization"), null);
});

test("always sets ngrok-skip-browser-warning: true", () => {
  assert.equal(applyEngineAuthHeaders(new Headers(), {}).get("ngrok-skip-browser-warning"), "true");
  assert.equal(
    applyEngineAuthHeaders(new Headers(), { apiKey: "k", tunnelBasicAuth: "u:p" }).get("ngrok-skip-browser-warning"),
    "true",
  );
});

test("all three headers present together in the prod configuration", () => {
  const h = applyEngineAuthHeaders(new Headers(), { apiKey: "key-123", tunnelBasicAuth: "jarvis:s3cret" });
  assert.equal(h.get("x-api-key"), "key-123");
  assert.equal(h.get("authorization"), "Basic " + Buffer.from("jarvis:s3cret").toString("base64"));
  assert.equal(h.get("ngrok-skip-browser-warning"), "true");
});
