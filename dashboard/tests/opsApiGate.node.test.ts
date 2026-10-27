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
