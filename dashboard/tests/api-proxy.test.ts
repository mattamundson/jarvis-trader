/**
 * P5.1 — real unit tests for the shared engine/master API-proxy core
 * (lib/api-proxy.ts), extracted from app/api/engine/[...path]/route.ts and
 * app/api/master/[...path]/route.ts specifically so it's loadable by Node's
 * native TS-stripping test runner — those route files import the bare
 * "next/server" specifier, which only Next's own bundler can resolve, not
 * `node --test`. Same convention as tests/position-sizing.test.ts /
 * tests/ask-jarvis-adapters.test.ts: real executed node:test, fetch
 * dependency-injected so no network is touched.
 *
 * Covers the two request/response security contracts named in the
 * checklist item: (1) the server-side API key is actually injected into the
 * upstream call when configured, and (2) no client-supplied header or
 * server secret ever leaks back into the response the browser receives —
 * ties into P5.2's e2e "no X-API-Key leaves the browser" assertion.
 *
 * Run via: node --test tests/api-proxy.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildTargetUrl,
  buildUpstreamHeaders,
  sanitizeUpstreamResponseHeaders,
  runProxy,
  type ProxyConfig,
} from "../lib/api-proxy.ts";

const ENGINE_CONFIG: ProxyConfig = {
  baseUrl: "http://127.0.0.1:8010",
  apiKey: "real-engine-secret",
  timeoutMs: 25_000,
  forwardClientHeaders: true,
  redirect: "manual",
  errorTag: "engine_proxy_failed",
};

const MASTER_CONFIG: ProxyConfig = {
  baseUrl: "http://127.0.0.1:8030",
  apiKey: "real-master-secret",
  timeoutMs: 55_000,
  forwardClientHeaders: false,
  errorTag: "master_proxy_failed",
};

test("buildTargetUrl joins the base, path segments, and query string", () => {
  const url = buildTargetUrl("http://127.0.0.1:8010", ["decisions", "recent"], "?limit=5");
  assert.equal(url.toString(), "http://127.0.0.1:8010/decisions/recent?limit=5");
});

test("buildUpstreamHeaders injects the server-side key onto the upstream call", () => {
  const clientHeaders = new Headers({ accept: "application/json" });
  const headers = buildUpstreamHeaders(ENGINE_CONFIG, clientHeaders);
  assert.equal(headers.get("X-API-Key"), "real-engine-secret");
});

test("buildUpstreamHeaders omits the header entirely when no key is configured (no 'undefined' leak)", () => {
  const clientHeaders = new Headers({ accept: "application/json" });
  const headers = buildUpstreamHeaders({ ...ENGINE_CONFIG, apiKey: undefined }, clientHeaders);
  assert.equal(headers.has("X-API-Key"), false);
});

test("buildUpstreamHeaders (engine, forwardClientHeaders=true) strips hop-by-hop headers but keeps the rest", () => {
  const clientHeaders = new Headers({
    host: "dashboard.local",
    connection: "keep-alive",
    "content-length": "42",
    accept: "application/json",
  });
  const headers = buildUpstreamHeaders(ENGINE_CONFIG, clientHeaders);
  assert.equal(headers.has("host"), false);
  assert.equal(headers.has("connection"), false);
  assert.equal(headers.has("content-length"), false);
  assert.equal(headers.get("accept"), "application/json");
});

test("buildUpstreamHeaders (master, forwardClientHeaders=false) drops every client header — nothing the browser sends reaches master-api", () => {
  const clientHeaders = new Headers({
    "x-api-key": "client-supplied-spoofed-key",
    cookie: "session=abc123",
    accept: "application/json",
  });
  const headers = buildUpstreamHeaders(MASTER_CONFIG, clientHeaders);
  assert.equal(headers.get("X-API-Key"), "real-master-secret");
  assert.equal(headers.has("cookie"), false);
  assert.equal(headers.has("accept"), false);
  assert.equal([...headers.keys()].length, 1);
});

test("sanitizeUpstreamResponseHeaders strips only hop-by-hop headers", () => {
  const upstreamHeaders = new Headers({
    "content-encoding": "gzip",
    "content-length": "123",
    "transfer-encoding": "chunked",
    "content-type": "application/json",
  });
  const headers = sanitizeUpstreamResponseHeaders(upstreamHeaders);
  assert.equal(headers.has("content-encoding"), false);
  assert.equal(headers.has("content-length"), false);
  assert.equal(headers.has("transfer-encoding"), false);
  assert.equal(headers.get("content-type"), "application/json");
});

test("runProxy sends the real key upstream but never returns it in the client-facing response", async () => {
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (_target, init) => {
    capturedInit = init;
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;

  const response = await runProxy(
    ENGINE_CONFIG,
    { method: "GET", headers: new Headers(), search: "" },
    ["health"],
    fetchImpl,
  );

  const sentHeaders = new Headers(capturedInit?.headers as HeadersInit);
  assert.equal(sentHeaders.get("X-API-Key"), "real-engine-secret");
  assert.equal(response.headers.has("X-API-Key"), false);
  assert.equal(response.status, 200);
});

test("runProxy on a client-supplied X-API-Key does not let it override the server key upstream", async () => {
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (_target, init) => {
    capturedInit = init;
    return new Response(null, { status: 204 });
  }) as typeof fetch;

  await runProxy(
    ENGINE_CONFIG,
    {
      method: "GET",
      headers: new Headers({ "X-API-Key": "client-supplied-spoofed-key" }),
      search: "",
    },
    ["health"],
    fetchImpl,
  );

  const sentHeaders = new Headers(capturedInit?.headers as HeadersInit);
  assert.equal(sentHeaders.get("X-API-Key"), "real-engine-secret");
});

test("runProxy returns 502 with a generic message (no key material) when the upstream fetch fails", async () => {
  const fetchImpl = (async () => {
    throw new Error("connect ECONNREFUSED 127.0.0.1:8010");
  }) as typeof fetch;

  const response = await runProxy(
    ENGINE_CONFIG,
    { method: "GET", headers: new Headers(), search: "" },
    ["health"],
    fetchImpl,
  );

  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error, "engine_proxy_failed");
  assert.ok(!JSON.stringify(body).includes("real-engine-secret"));
});

test("runProxy (master) never forwards a body-bearing init for its GET-only proxy", async () => {
  let capturedInit: RequestInit | undefined;
  const fetchImpl = (async (_target, init) => {
    capturedInit = init;
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  }) as typeof fetch;

  await runProxy(
    MASTER_CONFIG,
    { method: "GET", headers: new Headers(), search: "" },
    ["finances", "summary"],
    fetchImpl,
  );

  assert.equal(capturedInit?.body, undefined);
  const sentHeaders = new Headers(capturedInit?.headers as HeadersInit);
  assert.equal(sentHeaders.get("X-API-Key"), "real-master-secret");
});
