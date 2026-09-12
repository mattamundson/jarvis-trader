import { test, expect } from "@playwright/test";

function runtimeSnapshotFixture() {
  return {
    available: true,
    source: "phase0_runtime_truth_snapshot",
    generated_at: "2026-09-11T05:00:00Z",
    age_seconds: 600,
    freshness: "fresh",
    repository: { branch: "feat/market-brief-dashboard-card-20260911", head_short: "abcdef123456", dirty_count: 0 },
    contract: { artifact: "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT", schema_version: 1, required_sections_present: true, missing_sections: [] },
    ports: { engine_8010_open: true, dashboard_3010_open: true, ib_paper_4002_open: false, ib_live_4001_open: false },
    engine: { reachable: true, status: "ok", live_trading: false, paper_trading: true, kill_switch_active: true, ibkr_connected: false },
    backup: { reachable: true, healthy: true, backup_count: 7, last_backup_age_hours: 6 },
    eligibility: { reachable: true, total: 4, tradeable: 1, enabled: 1, disagreements: 0, enabled_not_tradeable: [], disagreeing_symbols: [] },
    source_integrity: { overall: "pass", pass_count: 1, fail_count: 0, unknown_count: 0, failing_labels: [], checks: [] },
    findings: ["Kill switch was active at capture time."],
    errors: { load: null },
  };
}

function marketBriefFixture() {
  return {
    mode: "ANALYSIS_ONLY",
    orders_enabled: false,
    risk_config_touched: false,
    asOf: "2026-09-11T01:00:00",
    generatedAt: "2026-09-11T01:00:00",
    sourcePath: "C:/Users/mattm/master-jarvis/second-brain/reports/night-shift/MORNING_BRIEF_MACHINE_SCORED_PREVIEW_2026-09-11.md",
    sourceQuality: "fresh",
    ageSeconds: 120,
    scores: {
      status: "computed",
      macro_event_count: 8,
      inputs: { trend_score: 0.6, vol_score: 1, macro_score: 1 },
      probabilities: { continuation: 79.5, rotation: 20.5, failure: 0 },
      notes: ["Scenario engine: continuation only upgrades with cross-asset acceptance; one-off touch does not imply regime change."],
    },
    symbols: {
      "ES=F": { provider: "yahoo", confidence: 0.8, gap_pct: 0.3, daily: { last_close: 7621.25 }, pivots: { pivot: 7616.75, r1: 7648, s1: 7567.25 } },
      "NQ=F": { provider: "yahoo", confidence: 0.8, gap_pct: 0.2, daily: { last_close: 29194.75 }, pivots: { pivot: 29228.92, r1: 29414.58, s1: 28949.58 } },
      SPY: { provider: "yahoo", confidence: 1, gap_pct: -0.6, daily: { last_close: 757.83 }, pivots: { pivot: 762.6, r1: 764.27, s1: 760.74 } },
      QQQ: { provider: "yahoo", confidence: 1, gap_pct: -1.06, daily: { last_close: 708.69 }, pivots: { pivot: 716.68, r1: 719.33, s1: 713.65 } },
      "^VIX": { provider: "yahoo", confidence: 1, gap_pct: 8.38, daily: { last_close: 17.84 }, pivots: { pivot: 16.24 } },
    },
    levels: [],
    warnings: [],
    modelVersion: "market-brief-machine-score-v1",
  };
}

test("mission-control renders market brief machine-score card as analysis-only", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 503, json: { detail: "engine mocked" } }));
  await page.route("**/api/fleet", (route) => route.fulfill({ status: 200, json: { canary: { overall: "GREEN", failing: [], generated_at: null }, counts: { total: 0, green: 0, red: 0, stale: 0 }, loops: [], red_loops: [], stale_loops: [], errors: {} } }));
  await page.route("**/api/runtime-snapshot", (route) => route.fulfill({ status: 200, json: runtimeSnapshotFixture() }));
  await page.route("**/api/spx-intraday", (route) => route.fulfill({ status: 200, json: { mode: "ANALYSIS_ONLY", orders_enabled: false, risk_config_touched: false, asOf: "2026-09-11T05:00:00Z", symbol: "SPX", proxyUsed: "SPY_PROXY", sourceQuality: "degraded", currentPrice: null, dayHigh: null, dayLow: null, dayChangePct: null, previousClose: null, vix: null, vixChangePct: null, rsi14: null, ema9: null, ema21: null, sma50: null, vwap: null, returns: {}, breadth: {}, levels: [], probabilityBands: null, scenarios: [], verdict: { label: "DATA_DEGRADED", confidence: 0, summary: "mocked", bullEvidence: [], bearEvidence: ["mocked"], invalidation: [] }, warnings: [], modelVersion: "mock" } }));
  await page.route("**/api/market-brief", (route) => route.fulfill({ status: 200, json: marketBriefFixture() }));

  await page.goto("/mission-control");

  const card = page.getByTestId("market-brief-card");
  await expect(card).toBeVisible();
  await expect(card.getByText("Market Brief Machine Score")).toBeVisible();
  await expect(card.getByText("ANALYSIS ONLY")).toBeVisible();
  await expect(card.getByText("CONTINUATION 79.5%")).toBeVisible();
  await expect(card.getByText("SPY gap")).toBeVisible();
  await expect(card.getByText("-0.60%").first()).toBeVisible();
  await expect(card.getByText("VIX Δ")).toBeVisible();
  await expect(card.getByText("+8.38%").first()).toBeVisible();
  await expect(card.getByText("7,616.75").first()).toBeVisible();
  await expect(card).not.toContainText(/order|execute|broker/i);
});
