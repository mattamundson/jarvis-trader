import { test, expect } from "@playwright/test";

test("regime smoke: renders sample fallback or live regime shell", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 503, json: { error: "engine unavailable" } }));

  await page.goto("/regime", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: /Intraday Market Regime/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Analyze|Analyzing/i })).toBeVisible();
  await expect(page.getByText(/SPY|QQQ|IWM|AAPL|NVDA|TSLA/i).first()).toBeVisible();
});
