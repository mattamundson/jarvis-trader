import { test, expect } from "@playwright/test";

test("health smoke: renders system health shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/health", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /System Health|Health/i })).toBeVisible();
});
