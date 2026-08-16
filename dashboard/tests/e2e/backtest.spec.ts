import { test, expect } from "@playwright/test";

test("backtest smoke: renders backtest results shell under empty engine data", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/backtest/results")) {
      return route.fulfill({ status: 200, json: [] });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/backtest", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: /JARVIS TRADER.*Backtest Results/i })).toBeVisible();
  await expect(page.getByText("Historical strategy performance")).toBeVisible();
  await expect(page.getByText(/No backtest results yet/i)).toBeVisible();
});
