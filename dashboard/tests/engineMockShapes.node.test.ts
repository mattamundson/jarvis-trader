import test from "node:test";
import assert from "node:assert/strict";

import { bodyFor } from "./e2e/_engineMock.ts";

test("generic engine mock exposes session-today shape", () => {
  const body = bodyFor("/api/engine/portfolio/stats/session-today") as Record<string, unknown>;

  assert.equal(body.session, "EXTENDED");
  assert.equal(body.closed_trades, 0);
  assert.equal(body.open_trades, 0);
  assert.equal(body.gross_pnl, 0);
  assert.deepEqual(body.symbols_traded, []);
});

test("generic engine mock exposes bar-quality shape", () => {
  const body = bodyFor("/api/engine/analytics/bar-quality?hours=168") as Record<string, unknown>;

  assert.equal(body.window_hours, 168);
  assert.equal(body.total_rejections, 0);
  assert.deepEqual(body.by_reason, []);
  assert.deepEqual(body.by_symbol, []);
  assert.deepEqual(body.by_path, { sanity: 0, gate: 0 });
  assert.deepEqual(body.recent, []);
});

test("generic engine mock exposes edge-ledger shape", () => {
  const body = bodyFor("/api/engine/reports/edge-ledger") as Record<string, unknown>;

  assert.equal(body.total, 0);
  assert.equal(body.n_pass, 0);
  assert.equal(body.n_fail, 0);
  assert.equal(body.n_other, 0);
  assert.deepEqual(body.rows, []);
});

test("generic engine mock exposes expanded data-integrity shape", () => {
  const body = bodyFor("/api/engine/system/data-integrity") as {
    status: string;
    stale_after_seconds: number;
    count: number;
    sources: unknown[];
    cache_age: { status: string };
    provider_tier: { status: string };
    bar_freshness: { status: string };
    source_parity: { status: string };
    trade_enablement: { status: string; blocking_reasons: string[] };
  };

  assert.equal(body.status, "degraded");
  assert.equal(body.stale_after_seconds, 900);
  assert.equal(body.count, 0);
  assert.deepEqual(body.sources, []);
  assert.equal(body.cache_age.status, "empty");
  assert.equal(body.provider_tier.status, "unknown");
  assert.equal(body.bar_freshness.status, "empty");
  assert.equal(body.source_parity.status, "not_wired");
  assert.equal(body.trade_enablement.status, "blocked");
  assert.deepEqual(body.trade_enablement.blocking_reasons, [
    "no_data_sources_reported",
    "cache_age_empty",
    "provider_tier_unknown",
    "bar_freshness_empty",
    "source_parity_not_wired",
  ]);
});
