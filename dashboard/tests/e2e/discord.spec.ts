import { test, expect } from "@playwright/test";

test("discord smoke: renders intelligence dashboard shell", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/discord", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: /Discord Intelligence/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Overview/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Signal Feed/i })).toBeVisible();
});
