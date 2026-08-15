// GT-13 regression test — /settings paper/live mode badge safety fix.
//
// WHY: the paper-vs-live badge is a safety-relevant indicator (is this
// account paper or live?). The original code was
// `config?.ibkr_paper_mode ?? data?.paper_mode ?? true` — `??` only falls
// through on null/undefined, so a stale `ibkr_paper_mode: false` sitting in
// the safety config would silently win over a disagreeing, more-trustworthy
// /health-derived `paper_mode` even when the two sources disagree. This
// locks resolvePaperMode() (lib/settings-api.ts) to the intended policy:
// prefer the /health-derived value, and flag any disagreement instead of
// silently picking one.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolvePaperMode } from "../lib/settings-api.ts";

test("resolvePaperMode: stale config `false` does not silently override a disagreeing health-derived `true`", () => {
  // The exact GT-13 repro: config says live (false, stale), /health says
  // paper (true, live/correct). The old `??` chain would have returned
  // `false` here because `false` is not null/undefined. It must not.
  const { paperMode, mismatch } = resolvePaperMode(
    { ibkr_paper_mode: false },
    { paper_mode: true }
  );
  assert.equal(paperMode, true, "must prefer the health-derived paper_mode over stale config");
  assert.equal(mismatch, true, "must flag that the two sources disagreed");
});

test("resolvePaperMode: stale config `true` does not silently override a disagreeing health-derived `false` (live)", () => {
  // Mirror case: config stale-says paper, health says live. This is the
  // more dangerous direction (silently showing PAPER while the account is
  // actually live) so it must resolve to the health value too.
  const { paperMode, mismatch } = resolvePaperMode(
    { ibkr_paper_mode: true },
    { paper_mode: false }
  );
  assert.equal(paperMode, false, "must prefer the health-derived paper_mode over stale config");
  assert.equal(mismatch, true, "must flag that the two sources disagreed");
});

test("resolvePaperMode: sources agree -> no mismatch flag, value passes through", () => {
  const agreeTrue = resolvePaperMode({ ibkr_paper_mode: true }, { paper_mode: true });
  assert.equal(agreeTrue.paperMode, true);
  assert.equal(agreeTrue.mismatch, false);

  const agreeFalse = resolvePaperMode({ ibkr_paper_mode: false }, { paper_mode: false });
  assert.equal(agreeFalse.paperMode, false);
  assert.equal(agreeFalse.mismatch, false);
});

test("resolvePaperMode: health missing -> falls back to config, no mismatch (only one source present)", () => {
  const result = resolvePaperMode({ ibkr_paper_mode: false }, undefined);
  assert.equal(result.paperMode, false);
  assert.equal(result.mismatch, false);
});

test("resolvePaperMode: config missing -> falls back to health, no mismatch (only one source present)", () => {
  const result = resolvePaperMode(undefined, { paper_mode: false });
  assert.equal(result.paperMode, false);
  assert.equal(result.mismatch, false);
});

test("resolvePaperMode: both sources missing -> defaults to paper (safe default)", () => {
  const result = resolvePaperMode(undefined, undefined);
  assert.equal(result.paperMode, true, "must default to the safe (paper) reading when no data is available");
  assert.equal(result.mismatch, false);
});
