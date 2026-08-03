import { test, expect } from "@playwright/test";

test("trade-history smoke: renders trade history shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/paper/validation/trades/closed") || url.includes("/paper/trades")) {
      return route.fulfill({ status: 200, json: [] });
    }
    if (url.includes("/master/trading/realized")) {
      return route.fulfill({
        status: 200,
        json: {
          headline: "debug",
          engine_sim: {
            ok: true,
            trade_list: [],
            net_realized: 0,
            wins: 0,
            losses: 0,
            win_rate: 0,
            profit_factor: null,
            gross_win: 0,
            gross_loss: 0,
            raw_rows: 0,
          },
          caveats: [],
        },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.route("**/api/master/**", (route) => {
    const url = route.request().url();
    if (url.includes("/master/trading/realized")) {
      return route.fulfill({
        status: 200,
        json: {
          headline: "debug",
          engine_sim: {
            ok: true,
            trade_list: [],
            net_realized: 0,
            wins: 0,
            losses: 0,
            win_rate: 0,
            profit_factor: null,
            gross_win: 0,
            gross_loss: 0,
            raw_rows: 0,
          },
          caveats: [],
        },
      });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trades", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Loading trades...")).toBeVisible({ timeout: 1000 });
  await expect(page.getByText("Loading trades...")).not.toBeVisible({ timeout: 10000 });
  await expect(page.getByRole("heading", { name: /Trade History/i }).first()).toBeVisible();
});
