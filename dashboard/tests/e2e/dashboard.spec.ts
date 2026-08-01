import { test, expect } from "@playwright/test";

test("dashboard route smoke: /dashboard resolves to command center content", async ({ page }) => {
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

  const url = page.url();
  const html = await page.content();

  if (url.includes("/command-center")) {
    await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
  } else {
    expect(html).toContain("/command-center");
  }
});
