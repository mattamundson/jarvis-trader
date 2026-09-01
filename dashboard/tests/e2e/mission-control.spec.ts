import { test, expect } from "@playwright/test";

test("mission-control smoke: redirects to Command Center operations view under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/mission-control", { waitUntil: "domcontentloaded" });

  await expect(page).toHaveURL(/\/command-center\?view=operations$/);
  await expect(page.getByText("Operations View").first()).toBeVisible();

  const body = (await page.textContent("body")) || "";
  expect(body).toContain("JARVIS TRADER");
  expect(body).not.toMatch(/something went wrong/i);
});
