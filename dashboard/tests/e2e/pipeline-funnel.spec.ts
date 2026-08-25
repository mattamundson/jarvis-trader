import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// Hermetic Pipeline Funnel card coverage. The two funnel windows (30d/90d) are
// route-mocked with payloads that match the engine's /analytics/pipeline-funnel
// contract exactly; every other engine call passes through to the live engine
// so the rest of the command-center renders as in production.

function loadCreds() {
  const p = path.resolve(__dirname, "../../.env.local");
  let user = "",
    pass = "";
  for (const line of fs.readFileSync(p, "utf8").split("\n")) {
    const m = line.match(/^DASHBOARD_AUTH_USER=(.*)$/);
    if (m) user = m[1].trim();
    const m2 = line.match(/^DASHBOARD_AUTH_PASS=(.*)$/);
    if (m2) pass = m2[1].trim();
  }
  return { user, pass };
}

const FUNNEL_30D = {
  period: "30d",
  days: 30,
  timestamp: "2026-08-25T18:00:00Z",
  funnel: { runs: 4766, signals: 285, approved: 159, executed: 28, filled: 28 },
  conversion_rates: {
    runs_to_signals: 6.0,
    signals_to_approved: 55.8,
    approved_to_executed: 17.6,
    executed_to_filled: 100.0,
    overall_conversion: 0.6,
  },
  details: {
    window_days: 30,
    cutoff: "2026-07-26T18:00:00",
    runs: 4766,
    signals: 285,
    approved: 159,
    executed: 28,
    filled: 28,
    human_approved: 1,
    human_rejected: 135,
    runs_to_signals_pct: 6.0,
    signals_to_approved_pct: 55.8,
    approved_to_executed_pct: 17.6,
    executed_to_filled_pct: 100.0,
    overall_conversion_pct: 0.6,
    cache_hit: false,
  },
};

const FUNNEL_90D = {
  period: "90d",
  days: 90,
  timestamp: "2026-08-25T18:00:00Z",
  funnel: {
    runs: 11168,
    signals: 1851,
    approved: 1553,
    executed: 87,
    filled: 87,
  },
  conversion_rates: {
    runs_to_signals: 16.6,
    signals_to_approved: 83.9,
    approved_to_executed: 5.6,
    executed_to_filled: 100.0,
    overall_conversion: 0.8,
  },
  details: {
    window_days: 90,
    cutoff: "2026-05-27T18:00:00",
    runs: 11168,
    signals: 1851,
    approved: 1553,
    executed: 87,
    filled: 87,
    human_approved: 387,
    human_rejected: 310,
    runs_to_signals_pct: 16.6,
    signals_to_approved_pct: 83.9,
    approved_to_executed_pct: 5.6,
    executed_to_filled_pct: 100.0,
    overall_conversion_pct: 0.8,
    cache_hit: false,
  },
};

test("command-center pipeline funnel card: 30d/90d stages, rates, and human lanes", async ({
  browser,
}) => {
  const { user, pass } = loadCreds();
  const context = await browser.newContext({
    httpCredentials: { username: user, password: pass },
  });
  const page = await context.newPage();

  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));

  // Mock only the funnel windows; everything else passes through to the live engine.
  await page.route("**/api/engine/analytics/pipeline-funnel*", (route) => {
    const url = route.request().url();
    if (url.includes("days=90")) {
      return route.fulfill({ status: 200, json: FUNNEL_90D });
    }
    return route.fulfill({ status: 200, json: FUNNEL_30D });
  });

  await page.goto("/command-center", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("pipeline-funnel-card")).toBeVisible();

  const card = page.getByTestId("pipeline-funnel-card");
  await expect(card.getByText("Pipeline Runs")).toBeVisible();

  // 30d counts (locale-formatted)
  await expect(card.getByText("4,766", { exact: true })).toBeVisible();
  await expect(card.getByText("285", { exact: true })).toBeVisible();
  await expect(card.getByText("28", { exact: true }).first()).toBeVisible();

  // 90d counts
  await expect(card.getByText("11,168", { exact: true })).toBeVisible();
  await expect(card.getByText("1,851", { exact: true })).toBeVisible();
  await expect(card.getByText("87", { exact: true }).first()).toBeVisible();

  // Conversion rates from both windows (regression surface)
  await expect(card.getByText("6.0%")).toBeVisible();
  await expect(card.getByText("83.9%")).toBeVisible();
  await expect(card.getByText("5.6%")).toBeVisible();

  // Overall conversion badges
  await expect(card.getByText("Overall Conversion")).toBeVisible();
  await expect(card.getByText("0.6%")).toBeVisible();
  await expect(card.getByText("0.8%")).toBeVisible();

  // Human-review lanes footnote (the "why so few trades" story)
  await expect(card.getByText(/human-approved 387 · rejected 310 \(90d\)/)).toBeVisible();

  // No page errors
  expect(pageErrors).toEqual([]);

  const shot = path.resolve(__dirname, "../../../.kanban-artifacts/pipeline-funnel-card.png");
  fs.mkdirSync(path.dirname(shot), { recursive: true });
  await card.screenshot({ path: shot });
  console.log(`SCREENSHOT:${shot}`);

  await context.close();
});
