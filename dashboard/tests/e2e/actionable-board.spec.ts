import { test, expect } from "@playwright/test";

// Hermetic ActionableBoardWidget coverage. Every engine call is route-mocked,
// so these tests assert the widget's own behavior and never depend on live
// engine/market state (a live board that suddenly has items would otherwise
// flip the empty-state assertions).

const EMPTY_POPULATED = {
  items: [],
  count: 0,
  available: true,
  raw_count: 5,
  shown: 0,
};

const EMPTY_QUEUE = {
  items: [],
  count: 0,
  available: true,
  raw_count: 0,
  shown: 0,
};

const REAL_ITEMS = {
  items: [
    {
      approval_id: "test-approval-1",
      symbol: "MES",
      direction: "long",
      action: "buy",
      approval_status: "approved",
      quantity: 1,
      confidence: 0.71,
      timeframe: "1h",
      created_at: "2026-08-25T10:00:00+00:00",
      age_days: 0,
      status: "triggerable",
      entry_price: 5000,
      stop_loss: 4985,
      target_1: 5060,
      atr: 10,
      latest_price: 5001.2,
      price_as_of: 1787680000,
      price_is_live: true,
      price_stale: false,
      distance_abs: -1.2,
      distance_pct: 0.024,
      distance_atr: 0.12,
      planned_rr: 4,
      current_r: 0.12,
      notional_per_contract: 25006,
    },
  ],
  count: 1,
  available: true,
  raw_count: 1,
  shown: 1,
};

function mockEngine(page, payload) {
  return page.route("**/api/engine/**", (route) => {
    const u = route.request().url();
    if (u.includes("/pipeline/actionable")) {
      return route.fulfill({ status: 200, json: payload });
    }
    // Everything else the page asks for is noise for these tests.
    return route.fulfill({ status: 200, json: {} });
  });
}

test.describe("ActionableBoardWidget", () => {
  test("explains WHY when the queue is populated but every row was filtered", async ({
    page,
  }) => {
    await mockEngine(page, EMPTY_POPULATED);
    await page.goto("/paper", { waitUntil: "domcontentloaded" });

    await expect(page.getByText(/Actionable Now/).first()).toBeVisible();

    // raw_count 5 + shown 0 must render the queue-state explanation, not a
    // bare "No actionable setups".
    const explanation = page.getByText(
      /The decision queue has 5 recent rows, but none qualify as actionable/
    );
    await expect(explanation).toBeVisible();
    await expect(explanation).toContainText("every recent decision was rejected");
  });

  test("explains WHY when the queue is genuinely empty (no recent decisions)", async ({
    page,
  }) => {
    await mockEngine(page, EMPTY_QUEUE);
    await page.goto("/paper", { waitUntil: "domcontentloaded" });

    await expect(page.getByText(/Actionable Now/).first()).toBeVisible();

    const explanation = page.getByText(
      /The decision queue has no recent directional decisions/
    );
    await expect(explanation).toBeVisible();
  });

  test("renders real entry/stop/T1 cards when data exists", async ({ page }) => {
    await mockEngine(page, REAL_ITEMS);
    await page.goto("/paper", { waitUntil: "domcontentloaded" });

    const card = page.locator('[data-testid="actionable-item"]');
    await expect(card).toHaveCount(1);
    await expect(card).toContainText("MES");
    await expect(card).toContainText("long");
    await expect(card).toContainText("triggerable");

    // Entry/stop/T1/T2 geometry must render with real numbers.
    await expect(card).toContainText("entry 5000.00");
    await expect(card).toContainText("stop 4985.00");
    await expect(card).toContainText("T1 5060.00");
    await expect(card).toContainText("last 5001.20");

    // Derived metrics render too.
    await expect(card).toContainText("planned RR 4.0");
    await expect(card).toContainText("current R +0.12");
    await expect(card).toContainText("conf 71%");
  });

  test("command-center page also mounts the actionable board", async ({
    page,
  }) => {
    await mockEngine(page, EMPTY_POPULATED);
    await page.goto("/command-center", { waitUntil: "domcontentloaded" });

    await expect(page.getByText(/Actionable Now/).first()).toBeVisible();
    await expect(
      page.getByText(/The decision queue has 5 recent rows, but none qualify as actionable/),
      { timeout: 15_000 }
    ).toBeVisible();
  });
});
