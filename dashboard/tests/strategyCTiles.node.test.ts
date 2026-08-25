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

test("missing metrics render as — (em dash), never a fabricated number, when offline", () => {
  // P6-3: a missing metric must render as visibly absent, not as a
  // plausible-looking invented figure (the old fallbacks were hardcoded
  // numbers like "3.75" / "$412,306.24" / "4.12×" that were
  // indistinguishable from real backtest output at a glance).
  const tiles = buildAdditionalMetricsTiles(undefined);

  assert.equal(tiles.length, 5);
  for (const tile of tiles) {
    assert.equal(tile.live, false, `${tile.label} should be marked non-live`);
    assert.equal(tile.value, "—", `${tile.label} should render —, got "${tile.value}"`);
  }
});

test("missing metrics render as — even when fullPeriod exists but individual fields are null", () => {
  const tiles = buildAdditionalMetricsTiles({
    sortino: null,
    calmar: null,
    win_rate: null,
    final_equity: null,
    final_multiple_x: null,
  });

  for (const tile of tiles) {
    assert.equal(tile.live, false);
    assert.equal(tile.value, "—");
  }
});

test("a partially-populated fullPeriod shows live values where present and — only where missing", () => {
  const tiles = buildAdditionalMetricsTiles({
    sortino: 2.5,
    calmar: null,
    win_rate: 0.55,
    final_equity: null,
    final_multiple_x: 4.123,
  });

  const byLabel = Object.fromEntries(tiles.map((t) => [t.label, t]));
  assert.equal(byLabel["Sortino"].live, true);
  assert.equal(byLabel["Sortino"].value, "2.50");
  assert.equal(byLabel["Calmar"].live, false);
  assert.equal(byLabel["Calmar"].value, "—");
  assert.equal(byLabel["Win Rate"].live, true);
  assert.equal(byLabel["Final Equity"].live, false);
  assert.equal(byLabel["Final Equity"].value, "—");
  assert.equal(byLabel["Final Multiple"].live, true);
  assert.equal(byLabel["Final Multiple"].value, "4.12×");
});
