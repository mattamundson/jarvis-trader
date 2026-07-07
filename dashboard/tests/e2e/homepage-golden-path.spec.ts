import { test, expect } from "@playwright/test";

// Golden path: under DEGRADED engine data (null prices + sparse/empty payloads)
// the overview must still render its core content and NEVER white-screen.
//
// What this guards:
//  - #163: SignalFlowWidget renders the em-dash for null prices instead of
//    crashing on `null.toLocaleString()`. If it had crashed, its boundary
//    fallback would replace its content and the "instruments" footer would be
//    absent -- so asserting that footer is present proves the #163 fix holds.
//  - Resilience: any OTHER widget that throws on sparse data is now isolated by
//    WidgetErrorBoundary ("... failed to render" card) rather than unwinding the
//    whole page to the route-level error fallback. (Hardening each of those
//    widgets to render gracefully is a separate follow-up.)
const NULL_PRICE = { last_price: null, prev_close: null, change_pct: null, error: "No data available" };

test("overview survives degraded engine data without white-screening", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/prices/snapshot")) {
      return route.fulfill({
        json: { MCL: { symbol: "MCL", ...NULL_PRICE }, MNQ: { symbol: "MNQ", ...NULL_PRICE }, MES: { symbol: "MES", ...NULL_PRICE } },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/", { waitUntil: "networkidle" });
  const body = (await page.textContent("body")) || "";

  // SignalFlowWidget rendered fully (its boundary did NOT replace it) => #163 fix holds.
  expect(body, "SignalFlowWidget did not render (its fallback or a page crash)").toContain("instruments: MCL / MNQ / MES");
  expect(body, "the SignalFlowWidget itself crashed into its boundary").not.toContain("Signal Flow failed to render");
  // The page did NOT collapse to the route-level error fallback (no white-screen).
  expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);
  // Null price renders the em-dash placeholder, not a crash.
  expect(body).toContain("—");
});
