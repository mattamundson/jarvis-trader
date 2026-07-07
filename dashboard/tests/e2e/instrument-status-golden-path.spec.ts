import { test, expect } from "@playwright/test";

// Golden path: the overview's RollingWFEWidget must render the real
// per-instrument status states production actually produces -- not just the
// "everything is fine" happy path homepage-golden-path.spec.ts already covers.
//
// Per engine/CLAUDE.md, MCL and MNQ are HALTED (DO_NOT_TRADE_SYMBOLS, WFE
// divergence) and M2K was REJECTED before ever reaching paper trading. The
// widget's actual status vocabulary (WFEInstrument.status in lib/api.ts) is
// "healthy" | "warning" | "critical" | "insufficient_data" -- HALTED
// instruments surface as "critical" (bear badge); an instrument rejected
// before accumulating any live trades surfaces as "insufficient_data" (info
// badge), since it never had a WFE window to compute. This test locks in
// that both edge states render their badge and never white-screen the page,
// the same regression class #163/#207 guard for null prices.
test("overview renders HALTED (critical) and never-traded (insufficient_data) instrument badges without crashing", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/paper/validation/wfe")) {
      return route.fulfill({
        json: {
          as_of: "2026-06-30T00:00:00Z",
          instruments: [
            {
              symbol: "MCL",
              current_wfe: 0.31,
              kill_threshold: 0.5,
              status: "critical",
              trades_in_window: 42,
              window_days: 30,
              current_pf: 0.71,
            },
            {
              symbol: "MNQ",
              current_wfe: 0.28,
              kill_threshold: 0.5,
              status: "critical",
              trades_in_window: 55,
              window_days: 30,
              current_pf: 0.64,
            },
            {
              symbol: "M2K",
              current_wfe: null,
              kill_threshold: 0.5,
              status: "insufficient_data",
              trades_in_window: 0,
              window_days: 30,
              current_pf: null,
            },
          ],
        },
      });
    }
    if (u.includes("/prices/snapshot")) {
      return route.fulfill({
        json: {
          MCL: { symbol: "MCL", last_price: 68.4, prev_close: 69.1, change_pct: -1.01 },
          MNQ: { symbol: "MNQ", last_price: 19850.5, prev_close: 19920.25, change_pct: -0.35 },
          MES: { symbol: "MES", last_price: 7459.25, prev_close: 7444.0, change_pct: 0.21 },
        },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/", { waitUntil: "networkidle" });
  const body = (await page.textContent("body")) || "";

  // HALTED instruments (MCL, MNQ) rendered their critical badge.
  expect(body, "MCL critical/HALTED badge did not render").toContain("MCL");
  expect(body, "CRITICAL badge text missing -- WFEBar status.toUpperCase() regressed").toContain("CRITICAL");

  // Never-traded/rejected instrument (M2K) rendered its insufficient-data badge
  // rather than crashing on a null current_wfe / current_pf.
  expect(body, "M2K insufficient-data badge did not render").toContain("M2K");
  expect(body, "INSUFFICIENT badge text missing -- null-WFE case regressed").toContain("INSUFFICIENT");

  // Page did not collapse to the route-level error fallback (no white-screen).
  expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
});
