import test from "node:test";
import assert from "node:assert/strict";

const { hit, runChecks } = await import("../scripts/check-live-data.mjs");

function response(status: number, body: unknown) {
  return {
    status,
    async json() {
      return body;
    },
  };
}

test("live checker uses canonical validation and Master API routes with separate keys", async () => {
  const calls: Array<{ url: string; key: string | undefined }> = [];
  const checks = [
    ["Validation", "http://engine", "/validation/status", "engine-key"],
    ["Master API", "http://master", "/master/health", "master-key"],
  ] as const;
  const fetchImpl = async (url: string, options: { headers?: Record<string, string> }) => {
    calls.push({ url, key: options.headers?.["X-API-Key"] });
    return response(200, { ok: true });
  };

  const result = await runChecks({ checks, fetchImpl, log: () => undefined });

  assert.equal(result.exitCode, 0);
  assert.deepEqual(calls, [
    { url: "http://engine/validation/status", key: "engine-key" },
    { url: "http://master/master/health", key: "master-key" },
  ]);
});

test("hit retries a transient timeout and then returns the live response", async () => {
  let attempts = 0;
  const fetchImpl = async () => {
    attempts += 1;
    if (attempts === 1) {
      const error = new Error("transient timeout");
      error.name = "AbortError";
      throw error;
    }
    return response(200, { price: 1 });
  };

  assert.deepEqual(await hit("http://engine", "/prices/snapshot", "key", fetchImpl), ["LIVE", "real data present"]);
  assert.equal(attempts, 2);
});

test("runChecks returns a status instead of force-exiting the Node process", async () => {
  const checks = [["Engine health", "http://engine", "/health", "key"]] as const;
  const result = await runChecks({
    checks,
    fetchImpl: async () => response(503, { error: "down" }),
    log: () => undefined,
  });

  assert.equal(result.exitCode, 1);
  assert.equal(result.rows[0].verdict, "UNREACHABLE");
});
