import { test, expect } from "@playwright/test";

test("trading-eligibility smoke: renders eligibility shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => {
    const url = route.request().url();
    if (url.includes("/paper/validation/approved-paper-gates")) {
      return route.fulfill({ status: 200, json: [] });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  await page.goto("/trading-eligibility", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /Trading Eligibility/i })).toBeVisible();
});
