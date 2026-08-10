import { test, expect } from "@playwright/test";

test("trade-signals smoke: renders signals shell under mocked engine", async ({ page }) => {
  await page.route("**/api/engine/**", (route) => route.fulfill({ status: 200, json: {} }));

  await page.goto("/signals", { waitUntil: "domcontentloaded" });

  const body = (await page.textContent("body")) || "";
  expect(body).toContain("Trade Signals");
  expect(body).not.toMatch(/something went wrong/i);
});
