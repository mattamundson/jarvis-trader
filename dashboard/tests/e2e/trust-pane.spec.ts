import { test, expect } from "@playwright/test";

test("trust-pane smoke: renders trust pane shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/trust-pane", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /Trust Pane/i })).toBeVisible();
});
