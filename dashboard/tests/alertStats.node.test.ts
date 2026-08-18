// GT-03 regression test: the Alert Log widget on /health must derive its
// sent/failed/pending counts from the REAL /alerts/stats shape
// ({stats: [{alert_type, status, count}], total}), not the
// {by_type, by_status, by_channel, total} shape it used to assume. That
// mismatch made `stats?.by_status?.failed` always undefined -> the widget
// showed "All OK, 0 Failed" even with a real 1,186 of 3,057 (38.8%) failed
// alerts in the DB. This fixture reproduces that same ratio.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { summarizeAlertStatusCounts, type AlertStatsRaw } from "../lib/alertStats.ts";

// Mirrors the real engine/routers/alerts_router.py GET /alerts/stats
// response: grouped by (alert_type, status), NOT a by_status lookup map.
const FIXTURE: AlertStatsRaw = {
  stats: [
    { alert_type: "signal", status: "sent", count: 1400 },
    { alert_type: "risk", status: "sent", count: 471 },
    { alert_type: "signal", status: "failed", count: 900 },
    { alert_type: "notification", status: "failed", count: 286 },
    { alert_type: "notification", status: "pending", count: 0 },
  ],
  total: 3057,
};

test("summarizeAlertStatusCounts: sums counts across alert_type for a given status (real 38.8% failure fixture)", () => {
  const counts = summarizeAlertStatusCounts(FIXTURE);
  assert.equal(counts.sent, 1871); // 1400 + 471
  assert.equal(counts.failed, 1186); // 900 + 286 -- the number the widget used to report as 0
  assert.equal(counts.pending, 0);
  assert.equal(counts.total, 3057);
  // The regression this test guards against: failed must be non-zero here.
  assert.ok(counts.failed > 0, "failed count must not collapse to 0 on a real mixed-status payload");
});

test("summarizeAlertStatusCounts: null/undefined input yields all-zero counts, not a throw", () => {
  assert.deepEqual(summarizeAlertStatusCounts(null), { sent: 0, failed: 0, pending: 0, total: 0 });
  assert.deepEqual(summarizeAlertStatusCounts(undefined), { sent: 0, failed: 0, pending: 0, total: 0 });
});

test("summarizeAlertStatusCounts: empty stats array yields zero counts but preserves total", () => {
  const counts = summarizeAlertStatusCounts({ stats: [], total: 0 });
  assert.deepEqual(counts, { sent: 0, failed: 0, pending: 0, total: 0 });
});

test("summarizeAlertStatusCounts: unknown status values are ignored, not folded into a bucket", () => {
  const counts = summarizeAlertStatusCounts({
    stats: [
      { alert_type: "signal", status: "sent", count: 10 },
      { alert_type: "signal", status: "suppressed", count: 5 }, // e.g. dedupe-suppressed
    ],
    total: 15,
  });
  assert.equal(counts.sent, 10);
  assert.equal(counts.failed, 0);
  assert.equal(counts.pending, 0);
  assert.equal(counts.total, 15);
});
