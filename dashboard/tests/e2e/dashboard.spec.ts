import { test, expect } from "@playwright/test";

test("dashboard route smoke: /dashboard resolves to command center content", async ({ page }) => {
  await page.goto("/dashboard");
  await page.waitForURL("**/command-center");

  await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
});
