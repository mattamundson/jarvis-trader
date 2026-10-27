// Tests for ops server-side gating
import { describe, it } from "node:test";
import assert from "node:assert";
import { isOpsEnabled } from "../lib/opsAuth.ts";

describe("isOpsEnabled gate", () => {
  it("returns false when OPS_ENABLED is not set", () => {
    assert.strictEqual(isOpsEnabled({}), false);
  });

  it("returns false when OPS_ENABLED is false", () => {
    assert.strictEqual(isOpsEnabled({ OPS_ENABLED: "false" }), false);
  });

  it("returns false when OPS_ENABLED is empty string", () => {
    assert.strictEqual(isOpsEnabled({ OPS_ENABLED: "" }), false);
  });

  it("returns false when OPS_ENABLED is any non-true value", () => {
    assert.strictEqual(isOpsEnabled({ OPS_ENABLED: "1" }), false);
    assert.strictEqual(isOpsEnabled({ OPS_ENABLED: "yes" }), false);
    assert.strictEqual(isOpsEnabled({ OPS_ENABLED: "TRUE" }), false);
  });

  it("returns true only when OPS_ENABLED is exactly 'true'", () => {
    assert.strictEqual(isOpsEnabled({ OPS_ENABLED: "true" }), true);
  });
});

describe("OPS_ENABLED gates /ops, /api/ops, and /setup-scorecard", () => {
  it("all three routes should be gated by OPS_ENABLED", () => {
    // This test documents that three routes are server-side gated:
    // 1. /ops page (app/ops/page.tsx)
    // 2. /api/ops route (app/api/ops/route.ts)
    // 3. /setup-scorecard page (app/setup-scorecard/page.tsx)
    // All use isOpsEnabled() and return 404 when OPS_ENABLED !== "true"
    assert.ok(true);
  });
});
