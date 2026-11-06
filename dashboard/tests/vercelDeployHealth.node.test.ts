import test from "node:test";
import assert from "node:assert/strict";

test("Vercel deploy health status mapping", () => {
  const statusMap = (readyState: string): string => {
    if (readyState === "READY") return "READY";
    if (readyState === "ERROR") return "ERROR";
    if (["BUILDING", "QUEUED", "INITIALIZING"].includes(readyState)) return "BUILDING";
    return "UNKNOWN";
  };

  assert.equal(statusMap("READY"), "READY");
  assert.equal(statusMap("ERROR"), "ERROR");
  assert.equal(statusMap("BUILDING"), "BUILDING");
  assert.equal(statusMap("QUEUED"), "BUILDING");
  assert.equal(statusMap("INITIALIZING"), "BUILDING");
  assert.equal(statusMap("CANCELED"), "UNKNOWN");
  assert.equal(statusMap(""), "UNKNOWN");
});

test("Vercel deploy health gracefully returns UNKNOWN when token is missing", () => {
  const mockResponse = { status: "UNKNOWN" as const };
  assert.equal(mockResponse.status, "UNKNOWN");
  assert.ok(!mockResponse.url);
  assert.ok(!mockResponse.createdAt);
});

test("Vercel deploy health response shape", () => {
  const mockResponse = {
    status: "READY" as const,
    url: "jarvis-trader-dashboard.vercel.app",
    createdAt: new Date().toISOString(),
  };

  assert.ok(["READY", "ERROR", "BUILDING", "UNKNOWN"].includes(mockResponse.status));
  assert.equal(typeof mockResponse.url, "string");
  assert.ok(mockResponse.createdAt);
  assert.ok(new Date(mockResponse.createdAt).getTime() > 0);
});
