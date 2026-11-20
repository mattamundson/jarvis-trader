// /tape truthfulness fixtures — frozen payload mocks, no live state files touched.
//
// Covers the 2026-11-07 audit fixes:
//  P1-1: "No divergence" must not render when there is no usable snapshot.
//  P2-1: recorder state + last-actual-tick age propagate; heartbeat never masquerades as a tick;
//        market closure is asserted only from the CME Globex schedule contract, never from idleness.
//  P1-2: stale / wrong-session / conflicting plans are UNAVAILABLE for actionable triggers and
//        shown as historical reference only — never auto-resolved, never silently dropped.
//
// Fixtures: tests/fixtures/tape/*.json (frozen, provenance in that directory's README).

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test, expect, type Page } from "@playwright/test";

const FIXTURE_DIR = join(__dirname, "..", "fixtures", "tape");

function loadFixture(name: string): string {
  return readFileSync(join(FIXTURE_DIR, name), "utf8");
}

test.beforeEach(async ({ page }) => {
  // Block unrelated API/WebSocket traffic so isolated UI tests never contact brokers/engine.
  await page.route('**/api/**', route => route.fulfill({status:503,contentType:'application/json',body:'{"error":"isolated fixture: unavailable"}'}));
  await page.routeWebSocket('**/*', socket => socket.close());
});

async function mockTapeApi(page: Page, fixture: string) {
  const body = loadFixture(fixture);
  await page.route("**/api/flow/tape", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "Cache-Control": "no-store" }, body });
  });
}

test("idle recorder on a scheduled-closed Saturday: divergence not evaluated, no false all-clear", async ({ page }) => {
  await mockTapeApi(page, "tape-idle-market-closed-20261107.json");
  await page.goto("/tape", { waitUntil: "domcontentloaded" });

  const alerts = page.getByTestId("tape-alerts");
  await expect(alerts.getByTestId("tape-alerts-unevaluated")).toHaveText(/No data — divergence not evaluated/);
  const alertsText = (await alerts.textContent()) ?? "";
  expect(alertsText).not.toContain("No divergence.");

  // Recorder state propagates; absent tick is stated, never rendered as current.
  await expect(page.getByTestId("tape-recorder-state")).toHaveText(/idle \(outside window\)/);
  await expect(page.getByTestId("tape-recorder-state")).toHaveText(/last tick: none this window/);

  // Market closed is asserted from the schedule contract, not from idleness.
  await expect(page.getByTestId("tape-market-state")).toHaveText(/closed per schedule/);
  await expect(page.getByTestId("tape-market-state")).not.toHaveText(/recorder idle — schedule says OPEN/);

  // The header stat shows "no tick" rather than a heartbeat-derived fresh age.
  await expect(page.getByTestId("tape-header")).toContainText("no tick");

  // Stale-plan (2026-11-03 fixture) is unavailable for triggers, shown as historical reference.
  await expect(page.getByTestId("tape-plan-unavailable")).toContainText("PLAN UNAVAILABLE FOR TRIGGERS");
  await expect(page.getByTestId("tape-plan-unavailable")).toContainText("stale");
  await expect(page.getByTestId("tape-plan-historical")).toContainText("Historical reference only");
  // The dashboard plan's own trigger levels (which conflict with the recorder's 7725.75 in this
  // fixture) render as historical reference.
  await expect(page.getByTestId("tape-plan-historical")).toContainText("7618.5");
  await expect(page.getByTestId("tape-trigger-long")).toHaveCount(0);
  await expect(page.getByTestId("tape-trigger-short")).toHaveCount(0);
  // No actionable status badge (TriggerCard renders data-status) anywhere in the trigger section.
  await expect(page.getByTestId("tape-triggers").locator("[data-status]")).toHaveCount(0);
});

test("current plan with live data: triggers evaluated normally, no unavailable banner", async ({ page }) => {
  await mockTapeApi(page, "tape-live-plan-current-ok.json");
  await page.goto("/tape", { waitUntil: "domcontentloaded" });

  await expect(page.getByTestId("tape-triggers")).toBeVisible();
  await expect(page.getByTestId("tape-plan-unavailable")).toHaveCount(0);
  await expect(page.getByTestId("tape-plan-head")).toContainText("2026-11-09");
  // A side card renders with an evaluated status (ARMED/TRIGGERED/FAILED), gated on live data.
  await expect(page.getByTestId("tape-trigger-long")).toBeVisible();

  // Recorder line shows an actual tick age and the open-window schedule label.
  await expect(page.getByTestId("tape-recorder-state")).toHaveText(/last tick/);
  await expect(page.getByTestId("tape-recorder-state")).not.toHaveText(/none this window/);
  await expect(page.getByTestId("tape-market-state")).toContainText("open per schedule");

  // With a usable snapshot, the alerts panel shows the evaluated line (or alerts), not "not evaluated".
  await expect(page.getByTestId("tape-alerts-unevaluated")).toHaveCount(0);
});

test("conflicting plan sources: explicit unavailable reason, never auto-resolved", async ({ page }) => {
  await mockTapeApi(page, "tape-live-plan-conflict-20261109.json");
  await page.goto("/tape", { waitUntil: "domcontentloaded" });

  await expect(page.getByTestId("tape-plan-unavailable")).toContainText("PLAN UNAVAILABLE FOR TRIGGERS");
  await expect(page.getByTestId("tape-plan-unavailable")).toContainText("not auto-resolved");
  await expect(page.getByTestId("tape-plan-historical")).toContainText("Historical reference only");
  await expect(page.getByTestId("tape-trigger-long")).toHaveCount(0);
  await expect(page.getByTestId("tape-triggers").locator("[data-status]")).toHaveCount(0);
});

test("unmocked API contract: recorder + schedule fields exist on the real endpoint", async ({ request }) => {
  // Real fresh-server transformation against fixture paths set by playwright.tape.config.ts.
  // No personal state files or running engine are read.
  const res = await request.get("/api/flow/tape");
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.recorder.state).toBe("idle (fixture)");
  expect(body.recorder.lastTickAgeS).toBeNull();
  if (body.ok) {
    expect(body.recorder).not.toBeNull();
    expect(typeof body.recorder.state === "string" || body.recorder.state === null).toBe(true);
    expect(body.recorder.lastTickAgeS === null || typeof body.recorder.lastTickAgeS === "number").toBe(true);
    expect(["scheduled_open", "scheduled_closed", "unknown"]).toContain(body.marketState.state);
    assertIsoDate(body.todayCt);
    assertIsoDate(body.globexTradingDate);
  } else {
    expect(body.marketState).toBeDefined();
    expect(body.recorder).toBeNull();
  }
});

for (const age of [null, 300, -1]) {
  test(`fresh heartbeat with actual tick age ${age}: no analytical all-clear or trigger`, async ({page}) => {
    const body=JSON.parse(loadFixture('tape-live-plan-current-ok.json'));
    body.recorder.lastTickAgeS=age;
    await page.route('**/api/flow/tape', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)}));
    await page.goto('/tape');
    await expect(page.getByTestId('stale-banner')).toBeVisible();
    await expect(page.getByTestId('tape-alerts-unevaluated')).toBeVisible();
    await expect(page.getByTestId('tape-trigger-long')).toHaveCount(0);
  });
}

test('Sunday calendar date with Monday session plan is eligible', async ({page})=>{
 const body=JSON.parse(loadFixture('tape-live-plan-current-ok.json'));
 body.todayCt='2026-11-08';
 await page.route('**/api/flow/tape', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)}));
 await page.goto('/tape');
 await expect(page.getByTestId('tape-plan-unavailable')).toHaveCount(0);
 await expect(page.getByTestId('tape-trigger-long')).toBeVisible();
});

function assertIsoDate(v: unknown) {
  expect(typeof v).toBe("string");
  expect(v as string).toMatch(/^\d{4}-\d{2}-\d{2}$/);
}
