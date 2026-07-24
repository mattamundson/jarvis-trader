// Regression test for GT-07: /discord Win Rate chart double-converted an
// already-percentage `avg_win_rate` field, showing 100% for every symbol
// (real spread 66-82%) and would render a real 76.63 value as "7663.0%".
//
// engine/routers/discord_router.py's `AVG(win_rate) as avg_win_rate` is on a
// 0-100 scale already (engine/discord/signal_context.py's own header
// comment: "The discord_bot_signals table stores win_rate as a percentage
// (0-100), not a ratio"). lib/discordWinRate.ts's `winRatePercent` is the
// single point of truth for turning that field into a display percent and
// must NOT re-multiply by 100.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { winRatePercent } from "../lib/discordWinRate.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// GT-07 lives on the /discord page in four call sites: the Win Rate chart
// (DiscordWinRateChart.tsx) and the import summary (import-stats.tsx) were
// fixed first; DiscordSignalTable.tsx (rendered unconditionally on the page)
// and signal-feed.tsx (rendered on the Signals tab) had the identical bug
// and are covered here. Source-scan them directly since these are JSX
// components with no DOM test runner wired into `pnpm run test:unit`
// (which only picks up *.node.test.ts) -- this still catches a regression
// where someone reintroduces `win_rate * 100` inline instead of calling
// the shared helper.
const DISCORD_COMPONENTS_DIR = path.join(__dirname, "..", "components", "discord");
const GT07_CALL_SITES = ["DiscordSignalTable.tsx", "signal-feed.tsx"];

for (const file of GT07_CALL_SITES) {
  test(`${file}: imports and uses the shared winRatePercent helper`, () => {
    const src = readFileSync(path.join(DISCORD_COMPONENTS_DIR, file), "utf8");
    assert.match(
      src,
      /import\s*\{\s*winRatePercent\s*\}\s*from\s*["']@\/lib\/discordWinRate["']/,
      `${file} must import winRatePercent from @/lib/discordWinRate`,
    );
    assert.match(
      src,
      /winRatePercent\(/,
      `${file} must call winRatePercent(...) to render win_rate`,
    );
  });

  test(`${file}: no raw double-percentage-conversion pattern remains`, () => {
    const src = readFileSync(path.join(DISCORD_COMPONENTS_DIR, file), "utf8");
    assert.doesNotMatch(
      src,
      /win_rate\s*\*\s*100/,
      `${file} must not re-multiply win_rate by 100 (GT-07 regression)`,
    );
    assert.doesNotMatch(
      src,
      /\brate\s*\*\s*100/,
      `${file} must not re-multiply a win-rate-derived value by 100 (GT-07 regression)`,
    );
  });
}

test("winRatePercent: passes an already-percentage value through unchanged", () => {
  // Real fixture shape: avg_win_rate is 0-100 already.
  assert.equal(winRatePercent(76.63).toFixed(1), "76.6");
  assert.notEqual(winRatePercent(76.63), 7663); // the GT-07 double-conversion bug
});

test("winRatePercent: 100 stays 100, not 10000", () => {
  assert.equal(winRatePercent(100), 100);
});

test("winRatePercent: null/undefined/NaN fall back to 0", () => {
  assert.equal(winRatePercent(null), 0);
  assert.equal(winRatePercent(undefined), 0);
  assert.equal(winRatePercent(NaN), 0);
});

test("winRatePercent: 0 stays 0 (falsy but valid)", () => {
  assert.equal(winRatePercent(0), 0);
});
