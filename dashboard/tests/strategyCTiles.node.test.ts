// GT-12 regression: the Strategy C+ "Final Equity" KPI tile used to render
// final_multiple_x (a 4.12x equity-curve multiple) under the "Final Equity"
// label, while the real dollar figure (final_equity) was fetched but never
// shown. Lock the tile-building logic so the label and the field it reads
// never drift apart again.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildAdditionalMetricsTiles,
  fmtUsdTile,
} from "../lib/strategyCTiles.ts";

test("Final Equity tile renders the dollar final_equity, not the multiple", () => {
  const tiles = buildAdditionalMetricsTiles({
    sortino: 2.5,
    calmar: 1.8,
    win_rate: 0.55,
    final_equity: 412306.24,
    final_multiple_x: 4.123,
  });

  const finalEquity = tiles.find((t) => t.label === "Final Equity");
  assert.ok(finalEquity, "expected a Final Equity tile");
  assert.equal(finalEquity!.value, fmtUsdTile(412306.24));
  assert.equal(finalEquity!.value, "$412,306.24");
  // The bug's signature: a "x" suffix leaking onto the dollar figure.
  assert.ok(!finalEquity!.value.includes("x"));
  assert.ok(!finalEquity!.value.includes("×"));
  assert.equal(finalEquity!.live, true);
});

test("Final Multiple gets its own separate, correctly-labeled tile", () => {
  const tiles = buildAdditionalMetricsTiles({
    final_equity: 412306.24,
    final_multiple_x: 4.123,
  });

  const finalMultiple = tiles.find((t) => t.label === "Final Multiple");
  assert.ok(finalMultiple, "expected a Final Multiple tile");
  assert.equal(finalMultiple!.value, "4.12×");
  assert.equal(finalMultiple!.live, true);

  const finalEquity = tiles.find((t) => t.label === "Final Equity");
  // The two tiles must never carry the same underlying value.
  assert.notEqual(finalEquity!.value, finalMultiple!.value);
});

test("Final Equity falls back to a Static dollar placeholder, not a multiple, when offline", () => {
  const tiles = buildAdditionalMetricsTiles(undefined);

  const finalEquity = tiles.find((t) => t.label === "Final Equity");
  assert.ok(finalEquity);
  assert.equal(finalEquity!.live, false);
  assert.ok(finalEquity!.value.startsWith("$"));
  assert.ok(!finalEquity!.value.includes("×"));

  const finalMultiple = tiles.find((t) => t.label === "Final Multiple");
  assert.ok(finalMultiple);
  assert.equal(finalMultiple!.live, false);
  assert.ok(finalMultiple!.value.includes("×"));
});
