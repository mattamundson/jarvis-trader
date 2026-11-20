// PR1013 secondary-surface integrity e2e (hermetic): the EXTRAS plan card and the LEAN
// tape screen. No real services, state files or broker calls — the extras tests route-mock
// /api/tape/extras, and the real-route gating case runs against the pinned synthetic
// fixture server (playwright.tape.config.ts, port 3015).
//
// Covers:
//  E1: a stale plan on the fixture server renders the extras plan card as
//      PLAN UNAVAILABLE FOR TRIGGERS with historical legs — never a TRIGGERED/TARGET/STOPPED badge.
//  E2: a gated-valid extras payload renders the main-evaluator state and its gate checks.
//  E3: lean accepts a fresh snapshot with an actual tick (no STALE) — heartbeat-only or
//      future clocks must NOT pass.
//  E4: lean withholds an unavailable plan's trigger/invalidation levels from the chart
//      overlay and states the reason.
//  E5: lean goes stale after a fetch failure even though the last good payload is cached.
//
// Fixture payloads are built relative to Date.now() so the freshness gates are exercised
// honestly (the same contract the production route serves).

import { test, expect, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // Block unrelated API/WebSocket traffic so isolated UI tests never contact brokers/engine.
  await page.route("**/api/**", (route) => {
    if (route.request().url().includes("/api/tape/extras") || route.request().url().includes("/api/flow/tape")) return route.fallback();
    return route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"isolated fixture: unavailable"}' });
  });
  await page.routeWebSocket("**/*", (socket) => socket.close());
});

const todayCt = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/Chicago" });

function leanPayload(over: Record<string, unknown> = {}) {
  const now = Date.now();
  const date = todayCt();
  return {
    ok: true,
    serverEpochMs: now,
    todayCt: date,
    globexTradingDate: date,
    planError: null,
    plan: {
      date,
      note: "synthetic e2e plan",
      nqRef: 21050,
      lookbackMin: 90,
      long: { trigger: 7618.5, minDelta: 150, targets: [7627], stop: 7611 },
      short: { trigger: 7597, minDelta: 150, targets: [7588], stop: 7604.5 },
      extraLevels: [],
    },
    recorder: {
      state: "recording (synthetic)", heartbeatAgeS: 2, lastTickAgeS: 1.2, reconnects: 0,
      connectedPort: 4002, sessionTradingDay: date, levelsSource: `tape-config (tape-plan dated ${date})`,
    },
    gex: null,
    gexError: "gex file unreadable",
    source: "synthetic fixture",
    sourceBars: null,
    file: "primary",
    fileAgeS: 4,
    stale10m: false,
    snapshot: {
      as_of_epoch: now / 1000 - 5,
      as_of_ct: new Date(now - 5000).toISOString(),
      price: { last: 7620, vwap: 7615, hi: 7625, lo: 7605 },
      cvd: { value: 1240 },
      nq: { rel: { last: 21061.25, lead: "NQ +11.25", windows: { "30m": { nq_pct: 0.21, es_pct: 0.18, rs: 0.03 } } } },
      levels: [],
      series_1m: [
        { t: Math.round(now / 1000) - 120, o: 7618, h: 7620, l: 7617, c: 7619, vol: 900, delta: 40, cvd: 600 },
        { t: Math.round(now / 1000) - 60, o: 7619, h: 7621, l: 7618, c: 7620, vol: 910, delta: 45, cvd: 645 },
      ],
    },
    ...over,
  };
}

async function mockFlow(page: Page, payload: object | ((req: any) => object), status = 200) {
  await page.route("**/api/flow/tape", async (route) => {
    if (status !== 200) return route.fulfill({ status, contentType: "application/json", body: '{"error":"fixture down"}' });
    const body = typeof payload === "function" ? (payload as (req: any) => object)(route.request()) : payload;
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "Cache-Control": "no-store" }, body: JSON.stringify(body) });
  });
}

async function mockExtras(page: Page, payload: object) {
  await page.route("**/api/tape/extras", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "Cache-Control": "no-store" }, body: JSON.stringify(payload) });
  });
}

function extrasPayload(over: Record<string, unknown> = {}) {
  return {
    snapshotMode: false,
    generatedAt: Date.now(),
    sources: { labels: {}, tape: { source: "synthetic", ageS: 4 }, plan: { source: "synthetic" } },
    ib: { light: "red", checks: [] },
    proof: { ok: false, error: "unavailable (synthetic)" },
    footprint: { ok: false, error: "unavailable (synthetic)" },
    footprintWide: { ok: false, error: "unavailable (synthetic)" },
    profile: { ok: false, error: "unavailable (synthetic)" },
    profileToday: { ok: false, error: "unavailable (synthetic)" },
    chart: { vwap: 7615, last: 7620, levels: [], priceSource: "synthetic", priceAgeS: 4 },
    plan: {
      ok: true, unavailable: false, reason: null, date: todayCt(), note: "synthetic", pastVoid: false,
      legs: [
        {
          side: "long", trigger: 7618.5, stop: 7611, targets: [7627],
          state: "TRIGGERED", historical: false,
          reason: "all three met, break bar 10:55",
          ifThen: "IF 5m closes above 7618.5 AND 1m delta >= +150 AND NQ above 21050 THEN targets 7627, stop under 7611",
          checks: [
            { label: "5m close above 7618.5", ok: true, detail: "last 5m close 7620.00 (+1.50)" },
            { label: "1m delta >= +150", ok: true, detail: "best +180 since break" },
            { label: "NQ above 21050", ok: true, detail: "NQ 21061.25 vs 21050 (+11.25)" },
          ],
          distance: 1.5,
        },
        {
          side: "short", trigger: 7597, stop: 7604.5, targets: [7588],
          state: "ARMED", historical: false, reason: "waiting on: 5m close below 7597", ifThen: null,
          checks: [{ label: "5m close below 7597", ok: false, detail: "last 5m close 7620.00" }],
          distance: -23,
        },
      ],
    },
    ...over,
  };
}

test("E1: fixture-server extras plan card for a stale plan is UNAVAILABLE and historical", async ({ page }) => {
  // Real /api/tape/extras route against the pinned synthetic fixture (plan dated 2026-11-03).
  await page.goto("/tape", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("plan-card")).toBeVisible();
  await expect(page.getByTestId("plan-card-unavailable")).toContainText("PLAN UNAVAILABLE FOR TRIGGERS");
  await expect(page.getByTestId("plan-leg-long")).toContainText("historical");
  // No actionable state badge ever renders for an unavailable plan.
  const legText = (await page.getByTestId("plan-leg-long").textContent()) ?? "";
  expect(legText).not.toContain("TRIGGERED");
  expect(legText).not.toContain("TARGET");
  expect(legText).not.toContain("STOPPED");
  const shortText = (await page.getByTestId("plan-leg-short").textContent()) ?? "";
  expect(shortText).toContain("HISTORICAL — NOT EVALUATED");
});

test('extras actual API withholds stale-plan overlays and does not read personal proof', async ({request}) => {
  const response=await request.get('/api/tape/extras');
  expect(response.status()).toBe(200);
  const body=await response.json();
  expect(body.plan.unavailable).toBe(true);
  expect(body.chart.levels.filter((l: any)=>['trigger','invalid','target','planref','level'].includes(l.kind))).toEqual([]);
  expect(body.proof.ok).toBe(false);
});

test('lean missing bar delta and CVD cannot draw zero-valued measurements', async ({page}) => {
  const payload=leanPayload();
  payload.snapshot.series_1m = payload.snapshot.series_1m.map(b=>({...b,delta:null,cvd:null,vol:null})) as any;
  await mockFlow(page,payload);
  await page.goto('/tape/lean');
  const chart=page.locator('svg').filter({hasText:'Δ 1m'});
  await expect(chart).toContainText('CVD unavailable');
  await expect(chart).toContainText('Delta unavailable');
  await expect(chart.locator('rect')).toHaveCount(0);
});

test("E2: gated-valid extras plan card renders main-evaluator states and gate checks", async ({ page }) => {
  await mockExtras(page, extrasPayload());
  await page.goto("/tape", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("plan-card")).toBeVisible();
  await expect(page.getByTestId("plan-card-unavailable")).toHaveCount(0);
  const long = page.getByTestId("plan-leg-long");
  await expect(long).toContainText("LONG · TRIGGERED");
  await expect(long).toContainText("1m delta >= +150 — best +180 since break");
  await expect(page.getByTestId("plan-leg-short")).toContainText("SHORT · ARMED");
});

test('extras cached valid card is withheld after fetch failure', async ({page})=>{
 let calls=0;
 await page.route('**/api/tape/extras', r => ++calls===1
   ? r.fulfill({status:200,json:extrasPayload()})
   : r.fulfill({status:500,json:{error:'fixture down'}}));
 await page.goto('/tape');
 await expect(page.getByTestId('plan-leg-long')).toContainText('TRIGGERED');
 await expect(page.getByTestId('tape-extras')).toContainText('UNAVAILABLE',{timeout:25000});
 await expect(page.getByTestId('plan-leg-long')).toHaveCount(0);
});

test('published extras snapshot never presents cached trigger state as current', async ({page})=>{
 await mockExtras(page,extrasPayload({snapshotMode:true}));
 await page.goto('/tape');
 await expect(page.getByTestId('plan-card-unavailable')).toBeVisible();
 await expect(page.getByTestId('plan-leg-long')).not.toContainText('TRIGGERED');
});

const LEAN_PANEL = "section";

test("E3: lean accepts a fresh snapshot with an actual tick (no STALE on the order-flow panel)", async ({ page }) => {
  await mockFlow(page, leanPayload());
  await page.goto("/tape/lean", { waitUntil: "domcontentloaded" });
  const flowPanel = page.locator(LEAN_PANEL).filter({ hasText: "Order flow" });
  await expect(flowPanel).toBeVisible();
  await expect(flowPanel).toContainText("age");
  await expect(flowPanel).not.toContainText("STALE");
  // A usable plan's trigger levels render as chart overlay text.
  await expect(page.locator("svg text").filter({ hasText: "Long trigger" })).toHaveCount(1);
});

test("E3b: lean rejects a future as_of_epoch (negative age is not fresh)", async ({ page }) => {
  const now = Date.now();
  await mockFlow(page, () => {
    const p = leanPayload() as any;
    p.snapshot.as_of_epoch = now / 1000 + 3600; // source clock 1h in the future
    return p;
  });
  await page.goto("/tape/lean", { waitUntil: "domcontentloaded" });
  const flowPanel = page.locator(LEAN_PANEL).filter({ hasText: "Order flow" });
  await expect(flowPanel).toContainText("STALE", { timeout: 15000 });
});

test("E4: lean withholds an unavailable plan's triggers from the chart overlay and says why", async ({ page }) => {
  const date = todayCt();
  const stale = new Date(Date.now() - 6 * 86400_000).toLocaleDateString("en-CA", { timeZone: "America/Chicago" });
  await mockFlow(page, leanPayload({
    plan: { ...(leanPayload().plan as object), date: stale },
    recorder: { state: "recording (synthetic)", heartbeatAgeS: 2, lastTickAgeS: 1.2, reconnects: 0, connectedPort: 4002, sessionTradingDay: date, levelsSource: `tape-config (tape-plan dated ${stale}, not today ${date} CT)` },
  }));
  await page.goto("/tape/lean", { waitUntil: "domcontentloaded" });
  const levelsPanel = page.locator(LEAN_PANEL).filter({ hasText: "Levels" });
  await expect(levelsPanel).toContainText("PLAN UNAVAILABLE FOR TRIGGERS");
  await expect(levelsPanel).toContainText("(plan unavailable)");
  // The plan trigger/invalidation levels are withheld from the actionable chart overlay.
  await expect(page.locator("svg text").filter({ hasText: "Long trigger" })).toHaveCount(0);
  await expect(page.locator("svg text").filter({ hasText: "Short trigger" })).toHaveCount(0);
  // GEX levels (fresh source, unavailable here) do not silently excuse the plan rows either.
  await expect(levelsPanel).toContainText("tape-plan");
});

test("E5: lean goes stale after a fetch failure even with a cached last-good payload", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/flow/tape", async (route) => {
    calls += 1;
    if (calls === 1) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(leanPayload()) });
    } else {
      await route.fulfill({ status: 500, contentType: "application/json", body: '{"error":"fixture down"}' });
    }
  });
  await page.goto("/tape/lean", { waitUntil: "domcontentloaded" });
  const flowPanel = page.locator(LEAN_PANEL).filter({ hasText: "Order flow" });
  await expect(flowPanel).not.toContainText("STALE");
  // Lean refreshes every 10s; after the failing poll the cached payload must read STALE.
  await expect(flowPanel).toContainText("STALE", { timeout: 20000 });
});
