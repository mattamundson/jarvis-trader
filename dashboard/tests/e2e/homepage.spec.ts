import { test, expect } from "@playwright/test";
import { installCommandCenterFixture } from "./command-center-fixtures";

test("homepage smoke: loads and contains JARVIS TRADER branding", async ({ page }) => {
  await installCommandCenterFixture(page, "empty");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/System Freshness/i)).toBeVisible();
  const body = (await page.textContent("body")) || "";
  expect(body).toContain("JARVIS TRADER");
});
