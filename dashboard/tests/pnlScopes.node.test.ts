import test from "node:test";
import assert from "node:assert/strict";

import { resolveDailyRealizedPnl } from "../lib/pnlScopes.ts";

test("prefers the explicit daily realized P&L field", () => {
  assert.equal(
    resolveDailyRealizedPnl({ daily_realized_pnl: -80.83, realized_pnl: 4977.07 }),
    -80.83,
  );
});

test("falls back to the legacy alias for older engines", () => {
  assert.equal(resolveDailyRealizedPnl({ realized_pnl: -80.83 }), -80.83);
});

test("does not fabricate zero when both fields are absent or invalid", () => {
  assert.equal(resolveDailyRealizedPnl({ daily_realized_pnl: null, realized_pnl: "bad" }), null);
});
