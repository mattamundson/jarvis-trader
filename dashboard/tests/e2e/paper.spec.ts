import { test, expect } from "@playwright/test";

test("paper smoke: renders paper trading shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/paper", { waitUntil: "domcontentloaded" });

  const body = (await page.textContent("body")) || "";
  expect(body).toContain("Paper Trading");
  expect(body).not.toMatch(/something went wrong/i);
});
