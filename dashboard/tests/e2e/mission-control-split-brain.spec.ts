import { test, expect } from "@playwright/test";

// Mission Control now redirects to the Command Center operations view. This
// keeps the old split-brain regression focused on the user-facing route while
// proving the reconciliation panel still renders after the redirect.
test("mission-control redirect renders the operations split-brain warn badge without white-screening", async ({
  page,
}) => {
  await page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/trading-status")) {
      return route.fulfill({
        status: 200,
        json: {
          summary: { total: 1, tradeable: 0, enabled: 1, disagreements: 1 },
          symbols: [
            {
              symbol: "MNQ",
              enabled: true,
              authorized: false,
              verdict: "PASS",
              verdict_family: "atr_trail",
              verdict_created_at: "2026-07-15T00:00:00Z",
              verdict_age_days: 18,
              oos_trades: 55,
              tradeable: false,
              config_agrees: false,
              disagreements: [
                "PAPER_CONFIGS.enabled=true but DO_NOT_TRADE_SYMBOLS blocks MNQ",
              ],
            },
          ],
        },
      });
    }
    // /decisions/recent and /portfolio/paper/positions/unrealized are
    // array-typed and already null-guarded in the other five panels
    // (`Array.isArray(decisions) ? decisions : []`, `positions ?? []`) --
    // an empty-object catch-all below is a safe, realistic "no data" 200 for
    // every other endpoint on this page.
    return route.fulfill({ status: 200, json: {} });
  });

  // EnvironmentFleetPanel reads the dashboard's own /api/fleet route (not
  // the engine proxy) -- mock it directly so the panel resolves deterministically
  // instead of depending on this worktree's real local filesystem state.
  await page.route("**/api/fleet", (route) =>
    route.fulfill({
      status: 200,
      json: {
        canary: { overall: "GREEN", failing: [], generated_at: null },
        counts: { total: 0, green: 0, red: 0, stale: 0 },
        red_loops: [],
        stale_loops: [],
        loops: [],
        errors: { registry: null, canary: null },
      },
    })
  );

  await page.goto("/mission-control", { waitUntil: "networkidle" });
  await expect(page).toHaveURL(/\/command-center\?view=operations$/);

  const body = (await page.textContent("body")) || "";
  expect(body, "flagship header did not render").toContain("JARVIS TRADER");
  expect(body, "operations view did not render after redirect").toContain("Operations View");
  expect(body, "page white-screened to the route error fallback").not.toMatch(/something went wrong/i);

  const mnqRow = page.locator("div", { hasText: /^MNQ/ }).filter({ hasText: "SPLIT-BRAIN" }).first();
  await expect(mnqRow, "MNQ's split-brain row did not render a SPLIT-BRAIN badge after mission-control redirect").toBeVisible();
  await expect(
    page.getByText("PAPER_CONFIGS.enabled=true but DO_NOT_TRADE_SYMBOLS blocks MNQ"),
    "the specific disagreement reason was not rendered after mission-control redirect"
  ).toBeVisible();
  await expect(page.getByText("1 split-brain")).toBeVisible();
});
