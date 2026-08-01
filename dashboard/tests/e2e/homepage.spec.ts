import { test, expect } from "@playwright/test";

test("homepage smoke: loads and contains JARVIS TRADER branding", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/System Freshness/i)).toBeVisible();
  const body = (await page.textContent("body")) || "";
  expect(body).toContain("JARVIS TRADER");
});
