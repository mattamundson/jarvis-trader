import assert from "node:assert/strict";
import { test } from "node:test";

import { summarizeMachinePayload } from "@/lib/marketBrief/summary";
import { toPublicMarketBrief } from "@/lib/marketBrief/public";
import { isPublicReadOnlyPath } from "@/lib/publicRoutes";

const payload = {
  generated_at: "2026-09-22T08:00:00Z",
  scores: {
    status: "computed",
    probabilities: { continuation: 52.5, rotation: 14.1, failure: 33.4 },
    probability_source: {
      primary: "trailing_unconditional_base_rate",
      conditional_status: "provisional_no_measured_edge",
      walkforward: { n: 1197, model_beats_base: false, paired_ci95: [-0.002225, 0.006517] },
    },
    conditional_diagnostic: {
      state: "not_ath_close",
      n: 1100,
      status: "provisional_no_measured_edge",
      publish_as_edge: false,
      probabilities: { continuation: 52.5, rotation: 14.1, failure: 33.4, sum: 100 },
    },
  },
  symbols: {
    "ES=F": { gap_pct: 0.1, daily: { last_close: 6600 }, pivots: { pivot: 6590 } },
    "^VIX": { gap_pct: -1.2, daily: { last_close: 16.2 }, pivots: { pivot: 16.5 } },
  },
};

test("public market brief snapshot strips sourcePath and preserves analysis-only safety", () => {
  const privateSnapshot = summarizeMachinePayload(payload, {
    sourcePath: "C:/Users/mattm/master-jarvis/second-brain/reports/night-shift/MORNING_BRIEF.md",
    nowMs: Date.parse("2026-09-22T08:01:00Z"),
  });
  const publicSnapshot = toPublicMarketBrief(privateSnapshot);
  const raw = JSON.stringify(publicSnapshot);

  assert.equal(publicSnapshot.mode, "ANALYSIS_ONLY");
  assert.equal(publicSnapshot.orders_enabled, false);
  assert.equal(publicSnapshot.risk_config_touched, false);
  assert.equal(publicSnapshot.publicContract.tradingControlsExposed, false);
  assert.equal(publicSnapshot.publicContract.localPathExposed, false);
  assert.equal(publicSnapshot.scores.probability_source?.primary, "trailing_unconditional_base_rate");
  assert.equal(publicSnapshot.scores.conditional_diagnostic?.publish_as_edge, false);
  assert.equal(publicSnapshot.scores.conditional_diagnostic?.status, "provisional_no_measured_edge");
  assert.ok(!raw.includes("C:/Users"));
  assert.ok(!raw.includes("sourcePath"));
});

test("public route allowlist excludes dashboard and engine control surfaces", () => {
  assert.equal(isPublicReadOnlyPath("/market-brief-public"), true);
  assert.equal(isPublicReadOnlyPath("/market-brief-public/history"), true);
  assert.equal(isPublicReadOnlyPath("/api/public-market-brief/latest"), true);

  assert.equal(isPublicReadOnlyPath("/mission-control"), false);
  assert.equal(isPublicReadOnlyPath("/api/market-brief"), false);
  assert.equal(isPublicReadOnlyPath("/api/engine/health"), false);
  assert.equal(isPublicReadOnlyPath("/command-center-v2/trade"), false);
});
